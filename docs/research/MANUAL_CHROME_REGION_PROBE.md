# 일반 Google Chrome 수동 지역 선택 진단

## 목적

GitHub Actions Chromium에서 검증된 지역 후보 버튼은 정상적인 클릭 이벤트를
수신해도 목표 지역이 검색 상태에 반영되지 않았습니다. 이 도구는 **일반 설치된
Google Chrome에서 사용자가 직접 지역을 선택했을 때** 같은 현상이 발생하는지
구분하기 위한 독립적인 대조 실험입니다.

**도구는 지역 선택을 자동화하지 않습니다.** Chrome을 실행하고 수동 클릭의
존재와 공개 검색 응답·화면의 지역 표시를 관찰할 뿐입니다. 매물 상세 페이지를
열거나 목록을 추출하지 않으며, 판매 가능 여부를 판단하지 않습니다.

## 안전 설계

- 설치된 일반 Google Chrome 실행 파일을 직접 호출합니다. Playwright가
  브라우저를 `launch`해 자동화 환경으로 실행하지 않습니다.
- 시스템 기본 Chrome 프로필은 **절대 재사용하지 않습니다**. 실행마다
  임시 빈 프로필을 만들고 종료 시 Chrome 프로세스를 닫고 프로필을 삭제합니다.
  Chrome 136+의 디버깅 보안 요구에 따라 `--user-data-dir`을 지정합니다.
- Chrome DevTools Protocol은 **127.0.0.1 + 운영체제가 선택한 임시 포트**
  에만 노출합니다. 포트 번호, WebSocket URL, 프로필 경로, 쿠키, 스토리지,
  요청 헤더, HAR를 로그나 출력 JSON에 기록하지 않습니다.
  **참고:** 실행 중에는 로컬 CDP 접속 권한이 높은 권한입니다. 신뢰할 수 있는
  개인 PC에서만 사용하고, 임시 프로필에서도 로그인하지 마세요.
- 네트워크 감시는 브라우저가 실제 생성한 공개 `/kr/search/buy-sell/`
  의 `q=HDD` GET Fetch/XHR, 목표 지역 키워드 공개 API로 제한합니다.
  새로운 API 요청, 비공개 엔드포인트 호출, 프록시, 로그인/인증 우회 없음.
- 응답 본문은 메모리에서만 최대 크기 제한하에 잠시 처리하며,
  검색 지역·필터 지역 ID와 지역 이름의 **일치 상태**만 추출합니다.
  매물 제목·내용·판매자·본문 URL·원시 숫자 ID를 반환·기록하지 않습니다.
- 검색 시작 시각이 실제 수동 클릭보다 이전인 응답은,
  클릭 **후에 완료됐더라도** 클릭에 따른 새 요청이라고 판단하지 않습니다.
- 출력은 고정 분류값, 제한된 카운트와 단계별 화면 상태뿐입니다.
  보고서에 `authorizes_listings: false`를 명시합니다.
- 관찰이 불명확하거나 차단 응답이 관찰되면 성공으로 간주하지 않습니다.
  수동 관찰 JSON을 OCI로 자동 전송하거나 GitHub에 업로드하지 않습니다.

## 실행 환경

- Windows 10/11 또는 macOS/Linux
- 일반 Google Chrome 설치
- Python 3.13, 저장소의 `requirements.txt` 설치
- 별도의 Playwright 브라우저 바이너리 설치는 **필요하지 않습니다**.
- 테스트 대상: 천안 지역 프리셋(불당동), 공개 검색 `HDD`.

Windows PowerShell에서:

```powershell
git clone https://github.com/mozzibara/auto-daangn.git
cd auto-daangn
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# 저장 없이 화면에서만 안전한 분류 결과 확인
python -m scripts.manual_chrome_region_probe

# JSON을 로컬 다운로드 폴더에 선택적으로 저장
python -m scripts.manual_chrome_region_probe --timeout-sec 150 --output "$HOME\Downloads\daangn_manual_region_result.json"
```

이미 저장된 결과는 **덮어쓰지 않으므로** 실행마다 다른 파일명을 사용하세요.
Chrome 경로를 찾지 못하면 다음처럼 명시할 수 있습니다.

```powershell
python -m scripts.manual_chrome_region_probe --chrome-path "C:\Program Files\Google\Chrome\Application\chrome.exe"
```

macOS/Linux는 같은 Python 모듈 명령으로 실행합니다. 시스템의
`google-chrome` 또는 `google-chrome-stable`, macOS 표준 앱 위치를 탐색합니다.

## 화면에서 수행할 일

1. 진단 명령을 실행하면 **새 임시 Chrome 창**이 열리고 공개 HDD 검색 페이지가 표시됩니다.
   Chrome 기존 로그인 세션·기존 확장 기능을 복사하지 않습니다.
2. 터미널에 **관찰 준비 완료**가 표시될 때까지 지역을 선택하지 마세요.
3. Chrome 창에서 **지역 선택 → 불당동 검색 → 천안시 불당동에 해당하는 후보
   버튼 직접 1회 선택**을 수행하세요.
4. 선택 후 다른 지역 버튼·확인 버튼을 누르거나 새로고침하지 마세요.
   브라우저에서 약 4초 동안 화면 변화와 서버 응답을 관찰합니다.
5. 수동 클릭을 검출하면 결과 JSON을 터미널에 출력하고 **진단 전용 Chrome 창을
   종료합니다**. 120초 동안 클릭이 없으면 `NO_TARGET_CLICK`으로 종료합니다.

자동 클릭, 강제 클릭, 키보드 우회 또는 반복 시도는 없습니다.
사이트에서 로그인이나 추가 인증을 요구하는 경우 **진행하지 말고**
그 상태를 보고하세요. 이 도구에는 로그인 정보 입력 기능이 없습니다.

## 결과 해석

- `manual_click.count=1` 및 `trusted_count=1`: 실제 사람이
  대화상자의 목표 지역 문구를 포함한 버튼을 한 번 눌렀다는 관찰값.
- `unique_candidate=true`, `city_hint=true`: 그 순간 후보가 유일하며
  버튼에 목표 도시 힌트가 포함됐다는 증거.
- `region_api.state=UNIQUE_EXPECTED_API_CANDIDATE`: 별도의 공개 지역
  후보 API가 프리셋의 목표 ID를 반환했다는 증거(숫자는 출력 안 함).
- `route.status=UNIQUE_POSTCLICK_ROUTE`: 수동 클릭 후 **새로 시작된**
  공개 검색 요청을 정확히 1건 확인하고 응답 구조를 판독했다는 의미.
- `route.search_region`, `route.filter_region`:
  각각 해당 서버 ID가 프리셋과 일치하면 `EXPECTED`, 다르면 `OTHER`.
- `stages.BEFORE` → `AT_CLICK` → `AFTER_200MS` →
  `AFTER_800MS` → `AFTER_2000MS` → `AFTER_4000MS`:
  대화상자/지역 버튼/검색창의 제한된 구조 변화.
  시점은 클릭 감지 이후의 **근사 샘플 간격**입니다.
- `comparison=UI_AND_ROUTE_EXPECTED_DIAGNOSTIC`: 수동 Chrome에서 실제
  클릭, 대상 후보 API, 화면 지역 표시와 클릭 후 신선한 Route 지역 ID가
  모두 일치하는 **대조 실험 결과**입니다. 수집기의 매물 승인 근거가 아닙니다.
- `comparison=UI_AND_ROUTE_OTHER`: UI와 신선한 서버 응답 모두
  대상이 아닌 지역을 가리킵니다. 일반 Chrome에서도 동일 현상이
  재현됐을 가능성이 높습니다.
- `INCONCLUSIVE` / `UI_ROUTE_DISAGREE` / 접근 차단:
  원인을 확정할 수 없고 추가적인 사용자 관찰이 필요합니다.

**비교 결과를 공유할 때는 이 도구가 출력한 JSON만 공유**하세요.
브라우저 프로필, DevTools HAR, 쿠키 파일, 실제 요청/응답 원문, 스크린샷에
포함된 계정 정보는 공유하지 마세요.

## 한계

- 이 도구는 **임시 비로그인 일반 Chrome**을 비교합니다. 평소 사용하던
  개인 프로필·로그인 세션과 반드시 같은 경험을 제공하는 것은 아닙니다.
  이 차이는 보안을 위해 의도적으로 유지됩니다.
- CDP 연결은 Playwright 프로토콜 연결보다 기능상 제약이 있으며,
  사이트 버전·동작이 바뀌면 `ROUTE_UNREADABLE`이나
  `INCONCLUSIVE`이 나올 수 있습니다.
- 수동 클릭을 누락하거나 중복해서 관찰하면 지역 확정 성공으로
  간주하지 않습니다. 관찰 불확실성은 실패가 아니라 불확실성으로 표시됩니다.
- 본 도구만으로 웹사이트의 로그인 요구 여부, React 내부 오류,
  봇 차단 원인을 확정할 수 없습니다.

## 근거

- Google Chrome 공식 안내(Chrome 136의 별도 프로필 요구):
  https://developer.chrome.com/blog/remote-debugging-port
- Playwright Python 공식 CDP 연결 문서:
  https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp

이 자료 및 자동화된 GH Actions 대조 실험은
[FRESH_REGION_AUTHORITY.md](FRESH_REGION_AUTHORITY.md)에서 함께 추적합니다.
