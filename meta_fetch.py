"""
메타 광고 데이터 자동 수집 스크립트
- 실행하면 대시보드 HTML 열림
- 작업 스케줄러에 등록해서 매일 자동 실행 가능
"""
import subprocess
import sys

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
DASHBOARD = r"C:\Users\zang0\Desktop\my-site\meta_dashboard.html"

print("리더뮨 광고 대시보드 열기...")
subprocess.Popen([CHROME, f"file:///{DASHBOARD}"])
print("완료")
