# 현재 시각을 KST(UTC+9) ISO-8601로 출력 — analyzer가 인덱스 _meta.generated_at을
# 실제 시각 대신 추측/고정값으로 채우던 문제를 막기 위해, 반드시 이 스크립트 실행 결과를
# 그대로 쓰도록 한다 (agents/analyzer.md Step 0 참조).
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


def now_kst():
    return datetime.now(KST).strftime("%Y-%m-%dT%H:%M:%S+09:00")


if __name__ == "__main__":
    print(now_kst())
