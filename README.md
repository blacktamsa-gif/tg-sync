Telegram Video Sync

GitHub Actions + Telethon으로 여러 Telegram 그룹/채널에서 새 동영상만 찾아 지정한 Telegram 그룹의 Forum Topic에 자동 업로드하는 프로젝트입니다.

1. 목표

현재 설정 개념:

A 채팅방 ─┐
          ├──> 대상 그룹의 Topic A
B 채팅방 ─┘

C 채팅방 ─┐
          ├──> 대상 그룹의 Topic B
D 채팅방 ─┘

A~D는 실제 이름이 아니라 설정용 임시 이름입니다.

2. 동작 규칙

A/B/C/D는 그룹 또는 채널 가능

소스 채팅방 내부의 Topic 이름은 고려하지 않음

모든 소스 Topic에서 동영상을 검색

동영상만 대상 그룹에 업로드

동영상의 caption/설명/텍스트는 업로드하지 않음

단독 이미지는 업로드하지 않음

이미지 + 동영상 앨범이면 동영상만 추출

같은 앨범에 동영상이 여러 개면 동영상들을 묶어서 업로드

텍스트/이미지/기타 파일은 업로드하지 않음

이미 처리한 메시지는 DB를 이용해 중복 업로드하지 않음

다운로드 또는 업로드가 실패한 경우 완료 처리하지 않아 다음 실행에서 재시도할 수 있도록 함

3. 실행 환경

VPS나 24시간 가동 서버를 사용하지 않습니다.

GitHub Actions
      ↓
Python + Telethon
      ↓
Telegram API
      ↓
A/B → Topic A
C/D → Topic B

GitHub Actions가 실행되는 동안만 프로그램이 동작합니다.

4. 프로젝트 구조

tg-sync/
├── .github/
│   └── workflows/
│       └── telegram.yml
├── src/
│   ├── main.py
│   └── database.py
├── requirements.txt
└── README.md

파일 역할

src/main.py

시간 계산

cutoff/lookback 계산

Telegram 로그인

소스 채팅방 검색

메시지/앨범 검색

동영상 판별

다운로드

Topic 업로드

처리 결과 DB 기록

로그 출력

src/database.py

SQLite state.db 관리

처리된 메시지 기록

중복 업로드 방지

필요한 DB 컬럼의 자동 마이그레이션

requirements.txt

Python 의존성 관리

.github/workflows/telegram.yml

GitHub Actions 예약/수동 실행

DB cache 복원/저장

5. GitHub Secrets

다음 Secret을 등록합니다.

API_ID
API_HASH
SESSION

TARGET_CHAT

SOURCE_A
SOURCE_B
SOURCE_C
SOURCE_D

TOPIC_A
TOPIC_B

총 10개입니다.

SESSION, API_HASH 등 민감한 값은 repository 파일에 직접 기록하지 않습니다.

6. Telegram ID

Supergroup/channel ID는 Telethon에서 보통 -100... 형태를 사용합니다.

예:

-1004321505833

처음 4321505833을 사용했을 때:

ValueError:
Could not find the input entity for PeerUser(...)

오류가 발생했고, -1004321505833 형태로 수정하여 해결했습니다.

7. Forum Topic 관련 문제

Telethon에서 다음 import는 실패했습니다.

from telethon.tl.functions.channels import GetForumTopicsRequest

확인 결과:

functions.channels.GetForumTopicsRequest → False
functions.messages.GetForumTopicsRequest → True

따라서 해당 API는 telethon.tl.functions.messages 쪽을 사용해야 합니다.

8. Telethon 버전

로컬에서는 Telethon 1.44.2를 사용했지만 GitHub Actions에서 Telethon==1.44.2 설치가 실패했습니다.

GitHub Actions 로그에서 사용 가능한 버전으로 1.44.0이 확인되어 현재 requirements는 다음을 사용합니다.

Telethon==1.44.0
cryptg==0.5.2

9. Cutoff

현재 최초 처리 기준은:

KST 2026-08-25 18:00:00

UTC:

2026-08-25 09:00:00

따라서 이 시점 이전의 동영상은 처리하지 않습니다.

로그:

[CUTOFF UTC] 2026-08-25T09:00:00+00:00
[CUTOFF KST] 2026-08-25 18:00:00+09:00

10. Lookback

현재 사용한 기본 lookback은:

70 minutes

예를 들어 Run 시각이:

2026-08-26 02:17:49 KST

이면 검색 시작 기준은:

2026-08-26 01:07:49 KST

입니다.

즉:

현재 시각
-
70분
=
검색 시작 시각

이며 cutoff보다 이전으로 내려가지 않도록 합니다.

11. 앨범 처리

Telegram에서 같은 grouped_id를 가진 메시지는 하나의 앨범 그룹으로 처리합니다.

예:

이미지
동영상
동영상
이미지

이면:

이미지 → 제외
동영상 → 업로드
동영상 → 업로드
이미지 → 제외

예전에 실제 로그에서 다음과 같이 확인되었습니다.

[GROUP MESSAGE IDS] [26365, 26366]
[GROUPED IDS] [14301392893849517, 14301392893849517]
[GROUP SIZE] 2
[GROUP VIDEO COUNT] 2

12. 정상 업로드 로그

정상적인 경우 다음과 같은 흐름이 나옵니다.

[GROUP VIDEO COUNT] 2

[CHECK DB] message=26365 processed=False
[CHECK DB] message=26366 processed=False

[NEW VIDEOS] 2

[DOWNLOAD START]
[DOWNLOAD SUCCESS]

[UPLOAD START] files=2
[UPLOAD MODE] caption=None
[UPLOAD MODE] reply_to=topic
[UPLOAD ALBUM] 1-2

[UPLOAD SUCCESS] videos=2
[DATABASE] marked=2

처리 순서는:

검색
 ↓
동영상 판별
 ↓
DB 확인
 ↓
다운로드
 ↓
업로드
 ↓
업로드 성공
 ↓
DB 기록

13. 로그 해석

영상이 없음

[GROUP VIDEO COUNT] 0
[SKIP] No video in this group.

→ 검색 범위에서 조건에 맞는 영상이 없었던 것.

새 영상 발견

[CHECK DB] message=12345 processed=False
[NEW VIDEOS] 1

→ 업로드 대상.

이미 처리됨

[CHECK DB] message=12345 processed=True

→ 중복 업로드하지 않음.

다운로드 실패

[DOWNLOAD START]
[DOWNLOAD ERROR] ...

→ 영상은 발견했지만 다운로드 실패.

업로드 실패

[UPLOAD START]
[UPLOAD ERROR] ...

→ 다운로드는 됐지만 Telegram 업로드 실패.

정상 완료

[UPLOAD SUCCESS]
[DATABASE] marked=...

→ 정상 처리.

14. 실제 테스트 결과

A 소스에서는 실제로 동영상 2개가 발견되어 정상적으로 업로드된 것이 확인되었습니다.

[GROUP VIDEO COUNT] 2
[NEW VIDEOS] 2
[DOWNLOAD SUCCESS]
[UPLOAD SUCCESS] videos=2
[DATABASE] marked=2

B/C/D에서 다음처럼:

[GROUP VIDEO COUNT] 0
[SKIP] No video in this group.

이 나온 경우는 업로드 실패가 아니라 해당 검색 범위에 조건에 맞는 영상이 없었던 것입니다.

15. DB / Cache

GitHub Actions runner는 영구 서버가 아니므로 처리 기록을 SQLite에 저장하고 GitHub Actions Cache로 보존합니다.

흐름:

Run #1
 ↓
src/state.db 생성/수정
 ↓
Cache 저장

Run #2
 ↓
Cache 복원
 ↓
기존 처리 기록 확인
 ↓
새 영상만 업로드
 ↓
DB 업데이트
 ↓
Cache 저장

현재 DB 경로는 반드시:

src/state.db

입니다.

따라서 workflow에서도:

path: src/state.db

를 사용해야 합니다.

예전에 path: state.db를 사용하여:

Path Validation Error

가 발생한 적이 있습니다.

16. DB 마이그레이션

개발 과정에서 DB 스키마가 변경되면서 기존 state.db에 새 컬럼이 없는 문제가 있었습니다.

현재 database.py는 필요한 컬럼이 없을 경우 자동으로 추가하는 마이그레이션을 사용합니다.

따라서 정상적인 경우 기존 처리 기록을 유지하면서 DB 구조를 업데이트할 수 있습니다.

17. GitHub Actions

권장 workflow 위치:

.github/workflows/telegram.yml

현재 권장 cron:

on:
  schedule:
    - cron: "17 * * * *"

  workflow_dispatch:

workflow_dispatch를 사용하면 Actions 화면에서 수동 실행할 수 있습니다.

18. Scheduled Run에 대한 주의

GitHub Actions의 schedule은 정밀한 실시간 타이머가 아닙니다.

예:

cron: "17 * * * *"

이면 매시간 17분을 기준으로 예약됩니다.

18:17
19:17
20:17
21:17
...

하지만 실제 시작 시각이 초 단위로 정확히 17분이라고 보장되지는 않습니다.

정각의 GitHub Actions 부하를 피하기 위해 0 * * * * 대신 17 * * * *를 사용하는 것을 권장합니다.

중요한 점:

Scheduled Run 자체가 생성되지 않음

이면 main.py 문제가 아닙니다.

반대로:

Scheduled Run 생성
 ↓
Python 실행
 ↓
Python 오류

이면 코드/Secret 등을 확인해야 합니다.

19. 수동 실행

GitHub:

Actions
→ Telegram Scheduled Video Processor
→ Run workflow

수동 실행은 다음처럼 표시됩니다.

Manually run by ...

자동 실행은:

Scheduled

로 표시됩니다.

20. 현재까지 해결된 주요 문제

API_ID 빈 값

ValueError:
invalid literal for int() with base 10: ''

원인: API_ID Secret 미설정 또는 빈 값.

Telegram ID

잘못된:

4321505833

수정:

-1004321505833

Forum Topic API

잘못된 위치:

telethon.tl.functions.channels

확인된 위치:

telethon.tl.functions.messages

Telethon 설치

GitHub Actions에서는:

Telethon==1.44.0

사용.

DB 함수/스키마

main.py와 database.py 버전이 서로 맞지 않으면:

ImportError

또는 DB schema 오류가 발생할 수 있으므로 변경된 파일은 항상 서로 호환되는 전체 버전으로 관리합니다.

21. Node 20 경고

다음과 같은 로그:

Node 20 is being deprecated.
This workflow is running with Node 24 by default.

는 GitHub Actions action runtime 관련 경고입니다.

Python/Telethon 오류와는 별개의 문제이며 workflow가 exit code 0으로 완료되고 Telegram 처리가 정상이라면 이 경고가 영상 업로드 실패의 원인은 아닙니다.

22. 보안

Repository에 직접 저장하지 않는 것:

API_ID
API_HASH
SESSION
실제 채팅방 정보
실제 Topic 정보

특히 SESSION과 API_HASH는 공개하지 않습니다.

실제 값은 GitHub Secrets로 관리합니다.

README와 소스 코드에는 가능하면:

SOURCE_A
SOURCE_B
SOURCE_C
SOURCE_D
TARGET_CHAT
TOPIC_A
TOPIC_B

같은 일반화된 이름을 사용합니다.

23. 운영 체크리스트

Telegram

API ID 발급

API Hash 발급

Session 생성

대상 그룹 ID 확인

Topic A ID 확인

Topic B ID 확인

Source A ID 확인

Source B ID 확인

Source C ID 확인

Source D ID 확인

GitHub Secrets

API_ID

API_HASH

SESSION

TARGET_CHAT

SOURCE_A

SOURCE_B

SOURCE_C

SOURCE_D

TOPIC_A

TOPIC_B

Repository

.github/workflows/telegram.yml

src/main.py

src/database.py

requirements.txt

README.md

실행 확인

수동 Run 성공

Telegram 로그인 성공

4개 Source 검색

동영상 판별

다운로드 성공

Topic 업로드 성공

DB 기록

Scheduled Run 생성 확인

24. 변경 관리 원칙

이 프로젝트에서는 코드 일부만 교체하지 않고 변경된 파일의 전체 코드를 교체하는 방식으로 관리합니다.

예:

main.py 수정
→ main.py 전체 파일 교체

database.py 수정
→ database.py 전체 파일 교체

telegram.yml 수정
→ telegram.yml 전체 파일 교체

특히 main.py와 database.py는 함수명과 DB schema가 서로 맞아야 합니다.

25. 최종 요약

이 프로젝트는:

GitHub Actions
   ↓
주기적으로 Python 실행
   ↓
Telethon으로 Telegram 접속
   ↓
A/B/C/D 소스 검색
   ↓
cutoff + lookback 범위 적용
   ↓
앨범/Topic 메시지 처리
   ↓
동영상만 추출
   ↓
이미지/텍스트/caption 제외
   ↓
대상 Topic에 업로드
   ↓
SQLite에 처리 기록
   ↓
GitHub Actions Cache로 상태 보존

하는 서버리스 Telegram 동영상 동기화 시스템입니다.

현재까지 실제 테스트에서 Telegram 로그인, 소스 검색, 앨범 인식, 동영상 판별, 다운로드, Topic 업로드, DB 기록까지 정상 동작하는 것이 확인되었습니다.

현재 가장 큰 운영상 주의점은 GitHub Actions Scheduled 실행 시간이 정확히 매시간 보장되지 않는다는 점입니다.
