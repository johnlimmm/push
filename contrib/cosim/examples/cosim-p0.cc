#include "../model/cosim-bridge.h"
// P0 공동 시뮬레이션의 C++ 참가자. Python의 FederationManager가 이 파일을 실행한다.
// 읽는 순서: main() → RunParticipant() → ADVANCE/INJECT 명령 처리.
// ns-3 코어 수정 없이, 단일 스레드 이벤트 루프를 요청된 시각까지만 진행한다.
// 양자 상태는 Python/NetSquid가 소유하며 여기서는 요청 도착과 결과 수신을 처리한다.
#include "ns3/command-line.h"
#include "ns3/cosim-agent-app.h"
#include "ns3/default-simulator-impl.h"
#include "ns3/map-scheduler.h"
#include "ns3/node.h"
#include "ns3/object-factory.h"
#include "ns3/simulator.h"

#include <sys/socket.h>
#include <unistd.h>

#include <cerrno>
#include <cstring>
#include <iostream>
#include <limits>
#include <map>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace ns3;
using namespace ns3::cosim;

namespace
{
using namespace ns3::cosim::bridge;

std::string Encode(const Result& result)
{
    std::ostringstream out;
    out << result.id << ' ' << result.processor << ' ' << result.state << ' '
        << result.code << ' ' << result.m1 << ' ' << result.m2;
    return out.str();
}

// 완료 결과를 앱이 실제 수신한 시각 + delayNs에 새 요청을 만드는 검증용 규칙.
// fired는 동일 완료 결과가 재전송돼도 후속 요청을 중복 생성하지 않도록 한다.
struct Followup
{
    uint64_t afterId;
    int64_t delayNs;
    Request request;
    bool fired{false};
};

void RunParticipant(Wire& wire)
{
    // ns-3의 내부 시간 단위도 ns로 맞춘 뒤, 한 이벤트씩 실행하는 어댑터를 설치한다.
    Time::SetResolution(Time::NS);
    Simulator::SetImplementation(CreateObject<SteppingSimulator>());
    ObjectFactory factory;
    factory.SetTypeId(VisibleScheduler::GetTypeId());
    Simulator::SetScheduler(factory);
    wire.Send("HELLO COSIM_P0 1");

    std::string tag;
    size_t processorCount, eventCount, followupCount;
    Parse(wire.Read(), tag, processorCount, eventCount, followupCount);
    Require(tag == "CONFIG" && processorCount > 0 && processorCount <= MAX_BATCH &&
                eventCount <= MAX_BATCH && followupCount <= MAX_BATCH,
            "invalid CONFIG");

    // 한 ADVANCE 경계에서 발생한 입력과 결과 수신 기록을 모아 Python에 반환한다.
    std::vector<Request> inputs;
    std::vector<Result> deliveries;
    std::vector<Followup> followups;
    std::map<uint32_t, Ptr<CosimAgentApp>> agents;
    std::vector<Ptr<Node>> nodes;
    auto schedule = [&](int64_t at, const Request& request) {
        auto it = agents.find(request.processor);
        // 잘못된 프로세서 ID도 원래 값을 유지해 양자 스케줄러가 정식 거절 응답을 만든다.
        auto app = it == agents.end() ? agents.begin()->second : it->second;
        Require(at >= Simulator::Now().GetNanoSeconds() && at <= MAX_TIME, "invalid arrival time");
        Simulator::Schedule(NanoSeconds(at - Simulator::Now().GetNanoSeconds()),
                            &CosimAgentApp::ReceiveRequest, app, request);
    };

    // 프로세서마다 ns-3 노드와 앱을 만든다. P0는 예약된 도착 이벤트로 앱을 호출한다.
    // 실제 패킷 수신 경로는 이후 단계에서 ReceiveRequest() 인터페이스에 연결한다.
    for (size_t i = 0; i < processorCount; ++i)
    {
        uint32_t id;
        Parse(wire.Read(), tag, id);
        Require(tag == "PROCESSOR" && !agents.count(id), "invalid PROCESSOR");
        auto node = CreateObject<Node>();
        auto app = CreateObject<CosimAgentApp>();
        node->AddApplication(app);
        app->SetRequestCallback([&](int64_t, const Request& request) { inputs.push_back(request); });
        app->SetResultCallback([&](int64_t at, const Result& result) {
            deliveries.push_back(result);
            if (result.state == "COMPLETED")
            {
                for (auto& followup : followups)
                {
                    if (!followup.fired && followup.afterId == result.id)
                    {
                        // delayNs=0이면 같은 시각에 다시 입력이 생긴다. 시간을 1 ns 밀지 않는다.
                        followup.fired = true;
                        Require(followup.delayNs <= MAX_TIME - at, "followup time overflow");
                        schedule(at + followup.delayNs, followup.request);
                    }
                }
            }
        });
        agents[id] = app;
        nodes.push_back(node);
    }
    for (size_t i = 0; i < eventCount; ++i)
    {
        int64_t at;
        Request request;
        Parse(wire.Read(), tag, at, request.kind, request.id, request.processor,
              request.pairA, request.pairB, request.durationNs);
        Require(tag == "EVENT", "expected EVENT");
        schedule(at, request);
    }
    for (size_t i = 0; i < followupCount; ++i)
    {
        Followup followup;
        auto& request = followup.request;
        Parse(wire.Read(), tag, followup.afterId, followup.delayNs, request.kind, request.id,
              request.processor, request.pairA, request.pairB, request.durationNs);
        Require(tag == "FOLLOWUP" && followup.delayNs >= 0, "invalid FOLLOWUP");
        followups.push_back(followup);
    }

    // 초기 이벤트 등록을 마쳤다. 이후 시간 진행 권한은 Python manager에 있다.
    wire.Send("READY 0 " + std::to_string(NextTime()));
    while (true)
    {
        std::string command = wire.Read();
        if (command == "QUIT")
        {
            wire.Send("BYE");
            break;
        }
        std::istringstream prefix(command);
        prefix >> tag;
        if (tag == "ADVANCE")
        {
            // manager가 고른 경계 이전에 ns-3 이벤트가 남아 있으면 건너뛰기를 거부한다.
            int64_t at;
            Parse(command, tag, at);
            const int64_t now = Simulator::Now().GetNanoSeconds();
            Require(at >= now && at <= MAX_TIME, "time reversal or overflow");
            Require(NextTime() == -1 || NextTime() >= at, "ADVANCE would skip an ns-3 event");
            if (at > now)
            {
                // 양자 완료만 있는 경계에도 ns-3 시계를 맞추기 위해 빈 이벤트를 예약한다.
                Simulator::Schedule(NanoSeconds(at - now), [] {});
            }
            size_t count = 0;
            // at의 이벤트와 그 이벤트가 at에 추가한 후속 이벤트까지 UID 순서로 배출한다.
            // SteppingSimulator 덕분에 at보다 미래의 이벤트를 실수로 실행하지 않는다.
            while (NextTime() == at)
            {
                Require(++count <= MAX_BATCH, "same-timestamp event limit exceeded");
                Simulator::Run();
            }
            Require(Simulator::Now().GetNanoSeconds() == at, "ns-3 boundary mismatch");
            std::ostringstream header;
            header << "BOUNDARY " << at << ' ' << NextTime() << ' ' << inputs.size() << ' '
                   << deliveries.size();
            wire.Send(header.str());
            for (const auto& request : inputs)
            {
                std::ostringstream row;
                row << "INPUT " << request.kind << ' ' << request.id << ' ' << request.processor
                    << ' ' << request.pairA << ' ' << request.pairB << ' ' << request.durationNs;
                wire.Send(row.str());
            }
            for (const auto& result : deliveries)
            {
                wire.Send("DELIVERED " + Encode(result));
            }
            inputs.clear();
            deliveries.clear();
        }
        else if (tag == "INJECT")
        {
            // 양자 응답을 현재 시각의 ns-3 이벤트로 예약한다. 이 명령은 시간을 진행하지 않는다.
            // 수신 콜백과 그에 따른 후속 요청은 같은 시각의 다음 ADVANCE에서 처리된다.
            int64_t at;
            size_t count;
            Parse(command, tag, at, count);
            Require(at == Simulator::Now().GetNanoSeconds() && count <= MAX_BATCH,
                    "invalid INJECT boundary");
            for (size_t i = 0; i < count; ++i)
            {
                Result result;
                Parse(wire.Read(), tag, result.id, result.processor, result.state, result.code,
                      result.m1, result.m2);
                Require(tag == "RESULT", "expected RESULT");
                auto it = agents.find(result.processor);
                auto app = it == agents.end() ? agents.begin()->second : it->second;
                Simulator::ScheduleNow(&CosimAgentApp::ReceiveResult, app, result);
            }
            wire.Send("INJECTED " + std::to_string(NextTime()));
        }
        else
        {
            throw std::runtime_error("unknown bridge command");
        }
    }
    Simulator::Destroy();
}
} // namespace

int main(int argc, char** argv)
{
    // run_p0.py가 socketpair의 자식 쪽 FD를 넘긴다. 단독 실행용 시나리오 인자는 없다.
    int bridgeFd = -1;
    CommandLine cmd(__FILE__);
    cmd.AddValue("bridgeFd", "Inherited Unix stream socket from the federation runner", bridgeFd);
    cmd.Parse(argc, argv);
    try
    {
        Require(bridgeFd >= 0, "launch with contrib/cosim/python/run_p0.py");
        Wire wire(bridgeFd);
        RunParticipant(wire);
        close(bridgeFd);
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << "cosim-p0: " << error.what() << '\n';
        Simulator::Destroy();
        return 1;
    }
}
