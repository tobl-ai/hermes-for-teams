# 일반 요청 자동 스케줄링 — 구현과 검증 범위

## 판정

**Experimental. 본체 연결 패치와 애드온이 함께 필요하다. 설치·owner 재기동·실제 호출 검증은 서로 다른 단계다.**

일반 메시지가 `teams_submit` 없이 실제 native ingress → 인증 → 기존 durable
SessionAuthority FIFO → 새 whole-turn scheduling seam → 기존 실행 경로로 흐른다.
별도의 CLI 질문으로 바꾸거나 `inject_message`로 재전송하지 않는다. 따라서 같은
세션의 기록, 원래 작성자, 그룹/스레드 라우팅, 첨부파일, 승인과 최종 전달의
소유권은 기존 Hermes가 그대로 유지한다.

실행 분산은 **기존 소유 프로필 안의 독립 native turn 동시 실행**이다. 다른
프로필·계정으로 이동하는 부하 분산이나 새 프로세스/원격 worker 격리는 아니다.

## 기존 extension으로만 불가능했던 부분

- `post_gateway_admission`: text/source snapshot만 제공하며 timeout/error에서
  fail-open. 콜백에서 별도 큐에 commit한 뒤 ACK가 유실되면 원본도 실행될 수 있다.
- `inject_message`: 원래 전체 MessageEvent/인증 주체/완료 receipt를 이관하는 API가
  아니다. 원래 작성자를 마지막 저장 작성자로 대체하지 않는다.
- LLM/tool 실행 middleware: 전체 turn의 history/도구/승인/물리 실행 수명 경계가 아니다.

따라서 별도 core worktree에 **선택적 `gateway_turn_execution` async middleware
종류 + 단일 실행 연결점**만 추가했다. 기존 hook의 fail-open 의미는 바꾸지 않았다.
공식 배포에 이미 존재하는 public API라고 주장하지 않는다.

## 구현된 경계

- addon `automatic_enabled: false` 기본값. 기존 explicit 큐 옵션/도구 허용과 독립.
- 활성화하면 `PluginContext.register_middleware`로 native turn continuation을 감싼다.
- owning-profile scope에서 등록된 callback만 선택한다. profile/session/admission ID와
  입력 UTF-8 byte 수만 callback에 전달한다. 메시지·media 경로·runner/DB handle은 안 준다.
- 기본 interactive 2 / background 1 예약석. 독립 대화는 두 lane 사이에서 겹쳐 실행.
  세션 순서는 기존 durable FIFO에 맡긴다. addon에 별도 conversation ID를 받지 않는다.
- callback은 native continuation을 한 번만 실행할 수 있다. callback 자체 결과는 답변으로
  사용하지 않는다. 실행 전 정책 오류는 admission failed, **fail-open 실행 없음**.
  실행 후 ACK 오류는 실제 native 결과/예외를 유지하고 재실행하지 않는다.
- 실행 후 waiter cancellation이 발생해도 native coroutine이 끝나기 전에는 좌석을
  반환하지 않는다. 반복 cancellation도 검사했다.
- `ManagedExecutionUnknown`은 in-process 좌석을 격리 보유한다. 자동 retry/replay 없음.
- `/stop`, `/approve`, `/deny`, `/reset`, plaintext approval은 원래 native 제어 경로가
  담당한다. 승인 무력화·auth 복사·모델/provider 변경 없음.

## 반드시 남아 있는 제약

1. **필수 seam은 upstream에 없다.** 이 버전의 `compat/` 패치를 호환되는 본체에
   적용해야 한다. 애드온만 공식 무수정 Hermes에 설치하면 자동 스케줄링은 작동하지 않는다.
2. 제한은 **등록된 addon 인스턴스 / event loop / 프로필** 단위다. 모든 프로필의 host-wide
   공용 제한, cross-process/cross-host placement, 인증 domain 간 이동은 구현하지 않았다.
3. heavy 분류는 입력 크기(`automatic_heavy_bytes`, 기본 4096)의 **휴리스틱**이다.
   짧은 프롬프트가 오래 걸리는 작업은 interactive 좌석을 차지할 수 있다. 따라서 임의
   workload에서 짧은 요청 지연을 보장하거나 실제 실행비용 예측을 했다고 주장하지 않는다.
4. 슬롯 대기 시 admission은 이미 claimed다. owner crash 시 실제 실행 전이어도 native
   정책에 따라 unknown으로 남을 수 있다. 안전을 위해 자동 replay하지 않는다.
5. unknown 좌석의 operator reconciliation/release API는 아직 없다. 재시작/disable로
   불확실성을 해소했다고 간주하면 안 된다. 물리 worker 및 native admission을 먼저 확인해야 한다.
6. message/admission 재전달 중복은 native ledger가 막는다. 독립 메시지가 같은 외부 API를
   변경할 때의 일반적 exactly-once/공유 자원 잠금까지 제공하지 않는다.
7. legacy 비-authority 경로, native safe-worker policy가 plugin middleware를 금지한 경로,
   별도 cron execution 경로 전체에 적용되었다고 주장하지 않는다. 격리를 낮추지 않았다.
8. 이 프로토타입은 in-process scheduling이다. 중단 불가능한 tool이 끝나지 않으면 좌석도
   반환되지 않는다. 별도 강제 timeout으로 좌석을 재활용하지 않는다.
9. 새 자동 경로의 실제 모델/플랫폼 E2E, 운영 모든 에이전트 적용, quota/100사용자 용량,
   독립 보안 리뷰는 미검증이다. Aube Studio를 켜지 않았고 unknown 기존 job도 재실행하지 않았다.

## 설정 예시 — 아직 운영에 적용하지 말 것

```yaml
plugins:
  entries:
    hermes-for-teams:
      settings:
        automatic_enabled: true
        automatic_interactive: 2
        automatic_background: 1
        automatic_heavy_bytes: 4096
        trusted_operator_tools: false
        allow_cli_workers: false
```

필요 조건: 별도 core seam 리뷰·적용, 실제 owner generation 확인, idle/drain safeguards,
프로필별 opt-in, 부모 운영자의 canary/rollout 승인. 이 문서는 배포 승인이나 설치 완료가 아니다.

## 검증 절차

`tests/test_automatic.py`를 먼저 작성하고 모듈 부재 RED를 확인한 뒤 구현했다.
unknown reservation도 별도 RED (`unknown_errors` 인자 없음) → GREEN으로 검증했다.
core seam도 모듈 부재 RED 후 구현했다. 통합 fixture의 첫 실행에서는 그룹 기본값이
작성자별 세션임을 발견해 **fixture에서만** shared group 모드를 명시했다. 실제 설정은 안 바꿨다.

```sh
"$HERMES_PYTHON" -m pytest tests -o addopts= -q
"$HERMES_PYTHON" scripts/verify_automatic.py \
  --core /absolute/path/to/patched-hermes \
  --scratch "$PRIVATE_SCRATCH" \
  tests/gateway/test_turn_scheduling.py \
  /absolute/path/to/hermes-for-teams/tests/test_automatic_native.py
```

verifier는 allowlist 환경과 독립 HOME/HERMES_HOME/TMPDIR를 만들고 실제 source를 import한다.
운영 credential/daemon/adapter 연결을 사용하지 않는다. native SQLite/ingress/승인·media
codec은 실제 구현이며, **최종 agent work만 테스트용 synthetic callback**이다.

새 native integration 검증: 일반 메시지 자동 실행, shared group의 다른 작성자 FIFO,
독립 short turn이 heavy turn보다 먼저 완료, 원래 작성자/이름/채팅/media bytes 보존,
중복 message 재전송의 실행 1회, unauthorized ingress 차단, 정책 오류 terminal failed,
100개 일반 요청 unique completion과 bounded synthetic executor.

core 추가 검증: no callback 기본 동작, fail-closed, continuation 1회, ACK 손실 후 원결과,
위조 short-circuit 거부, 반복 cancellation 중 물리 작업 join, native 예외 삼키기 금지,
멀티프로필 owning scope 및 동일 row 객체 보존. 기존 media/approval/stop 회귀도 별도로 실행했다.

100 fixture는 SQLite+native ingress 스케줄링 검증일 뿐 모델 처리량이 아니다. raw JSON은
verifier의 출력 `EVIDENCE` 디렉터리 아래 `tmp/**/synthetic-100.json`에 보존된다.

### 확인한 실행 결과

- addon 전체: `26 passed, 1 skipped` (3.45s). 미패치 host에서 native seam 통합 모듈은 skip.
- core seam + 실제 `PluginContext`의 전체 `plugin.register(ctx)` 연결 + native fixture:
  `12 passed` (2.69s), evidence `automatic-offline-3ixhun01`.
- core/native/media/approval/stop 선택 회귀 최종: `74 passed, 1 skipped` (18.84s),
  evidence `automatic-offline-bdspg4_g`. 실제 전체 `plugin.register(ctx)` 연결, native
  제어 명령 5종의 scheduler 우회, safe-worker에서 plugin discovery 자체를 하지 않는
  회귀를 포함한다. 전체 core suite green을 주장하지 않는다.
- 해당 100 native synthetic fixture: requested=100, unique_completed=100,
  peak_synthetic_executor=1, wall=1.5720216670015361s. 예약석 1인 시험 설정이며
  기존 native baseline 2개 겹침 → addon 활성 시 두 번째 실행 대기 비교도 별도 검증했다.
- 위 evidence 디렉터리는 내부 scratch
  `$PRIVATE_SCRATCH` 아래에 있다.
- 두 worktree `git diff --check` 통과. 운영 checkout와 부모 addon checkout의
  `git status --porcelain`은 비어 있었다. 새 commit/publish/install은 하지 않았다.

- 메타데이터의 `physical_completion`은 별도의 물리 종료 신호다. native inactivity
  timeout이 먼저 반환돼도 실제 executor의 `worker_done` 전까지 예약석을 보유한다.
  timeout 응답 자체는 막지 않는다. 실제 executor helper + background thread로 RED→GREEN 검증했다.
- explicit existing-owner adapter는 `unattended=False`를 유지한다. 실제 frontend가
  `prompt.submit`에 `unattended=True`를 보내지 않는 회귀로 YOLO 우회를 차단했다.

## 초기 검증에서 발견해 수정한 source blocker

기존 `tui_gateway/methods_onboarding.py`의 누락된 `Path` import를 별도 RED로 재현한 뒤
import 한 줄과 import 회귀 테스트로 수정했다. 이후 authority/automatic/media/approval/stop
선택 검증에서 **62 passed, 2 skipped (14.82s)**를 확인했다. 이 결과를 전체 core suite나
실제 모델 100명 시험으로 확대 해석하지 않는다.
