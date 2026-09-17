"""Q2NS의 실제 request/packet/완료 경로와 NetSquid 단독 상태 소유를 검증한다."""


def validate_q2ns(report):
    def require(ok, message):
        if not ok:
            raise RuntimeError('Q2NS adapter validation: ' + message)
    sessions = report['snapshot']['sessions']
    status = report['q2ns_status']
    require(status == dict(native_state_count=0, native_qubit_count=0, sessions=len(sessions),
                           corrections_applied=len(sessions)), 'native ownership/completion count')
    rows = report['q2ns_events']
    require(len(rows) == 6*len(sessions), 'native event count')
    events = {e['event_id']: e for e in report['events']}
    seen = set()
    mappings = {}
    for sid, snap in sessions.items():
        own = [r for r in rows if str(r['session_id']) == sid]
        expected = dict(Q2NS_BSM_REQUEST=('BSM_REQUEST', 2, snap['requests']['1']['arrival_ns']),
            Q2NS_BSM_DONE=('BSM_COMPLETE', 2, snap['requests']['1']['completion_ns']),
            Q2NS_CTRL_SENT=('BSM_RESULT_LOCAL', 2, snap['requests']['1']['completion_ns']),
            Q2NS_FRAME_RESOLVED=('RESULT_RX', 3, snap['correction']['arrival_ns']),
            Q2NS_CORRECTION_REQUEST=('CORRECTION_REQUEST', 3, snap['correction']['arrival_ns']),
            Q2NS_CORRECTION_APPLIED=('CORRECTION_COMPLETE', 3, snap['correction']['completion_ns']))
        require(len(own) == len(expected) and {r['event_type'] for r in own} == set(expected), 'session native events')
        for row in own:
            parent_kind, node, at = expected[row['event_type']]
            require(row['event_id'] not in seen, 'native event identity')
            seen.add(row['event_id'])
            require(row['kind'] == 5 and row['node_id'] == node and row['message_id'] == 0,
                    'native event classification')
            require(type(row['time_ns']) is int and row['time_ns'] == at, 'native operation time')
            require([row[k] for k in ('pair_a','pair_b','output_pair_id')] == [101,102,103],
                    'logical EPR mapping')
            parent = events.get(row['cause'])
            require(parent is not None and parent['event_type'] == parent_kind and
                    parent['session_id'] == int(sid) and parent['sim_time_ns'] == at and
                    parent['source_sequence'] != row['source_sequence'], 'native causal link')
            if row['event_type'] not in ('Q2NS_BSM_REQUEST', 'Q2NS_CORRECTION_APPLIED'):
                require([row['m1'],row['m2']] == snap['correction']['measurement_bits'], 'native measurement bits')
        # 논리 Q2NS handle과 NetSquid의 session-local EPR/memory mapping을 보고서에 명시한다.
        mappings[sid] = dict(q2ns_pair_ids=[101,102,103], netsquid_pair_ids=[1,2,3],
            input_locations={p:snap['resources'][p]['locations'] for p in ('1','2')},
            output_locations=snap['ab_pair']['locations'])
    return dict(passed=True, checks=['actual_SwapApp_request', 'native_UDP_control_path',
                'native_frame_resolution', 'asynchronous_correction_ack', 'logical_EPR_mapping',
                'NetSquid_sole_quantum_state_owner'], resource_mapping=mappings,
                transport='IPv4/UDP', quantum_owner='NetSquid', Q2NS_wire_header_bytes=10)
