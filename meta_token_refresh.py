"""
메타 액세스 토큰 자동 갱신 스크립트
- Windows 작업 스케줄러로 자동 실행됨
- 새 토큰 발급 후 meta_config.json + meta_dashboard.html 자동 업데이트
"""
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "meta_config.json"
LOG_PATH    = Path(__file__).parent / "meta_refresh_log.txt"

def log(msg):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8-sig") as f:
        f.write(line + "\n")

def main():
    # config 읽기
    with open(CONFIG_PATH, encoding="utf-8-sig") as f:
        config = json.load(f)

    # 만료까지 7일 이상 남았으면 건너뜀
    expires_dt = datetime.strptime(config["expires_date"], "%Y-%m-%d")
    days_left  = (expires_dt - datetime.now()).days
    if days_left > 7:
        log(f"갱신 불필요 (만료까지 {days_left}일 남음) - 스킵")
        return

    log(f"=== 토큰 갱신 시작 (만료까지 {days_left}일) ===")

    app_id      = config["app_id"]
    app_secret  = config["app_secret"]
    old_token   = config["access_token"]
    dash_path   = Path(config["dashboard_path"])

    # 메타 API 호출 - 장기 토큰 교환
    resp = requests.get(
        "https://graph.facebook.com/v21.0/oauth/access_token",
        params={
            "grant_type":        "fb_exchange_token",
            "client_id":         app_id,
            "client_secret":     app_secret,
            "fb_exchange_token": old_token,
        }
    )
    data = resp.json()

    if "access_token" not in data:
        log(f"실패: {data.get('error', data)}")
        return

    new_token   = data["access_token"]
    expires_sec = data.get("expires_in", 5184000)
    expires_dt  = datetime.now() + timedelta(seconds=expires_sec)
    expires_str = expires_dt.strftime("%Y-%m-%d")

    log(f"새 토큰 발급 성공 (만료: {expires_str})")

    # config 업데이트
    config["access_token"]  = new_token
    config["expires_date"]  = expires_str
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    log("meta_config.json 업데이트 완료")

    # 대시보드 HTML 토큰 교체
    html = dash_path.read_text(encoding="utf-8")
    if old_token in html:
        html = html.replace(old_token, new_token)
        dash_path.write_text(html, encoding="utf-8")
        log("meta_dashboard.html 토큰 교체 완료")
    else:
        log("경고: HTML에서 기존 토큰을 찾지 못함 - 수동 확인 필요")

    log("=== 갱신 완료 ===\n")

if __name__ == "__main__":
    main()
