import threading
import time
import webbrowser
import uvicorn

HOST = "127.0.0.1"
PORT = 8000
URL = f"http://{HOST}:{PORT}"

def open_browser():
    time.sleep(1.2)
    webbrowser.open(URL)

def main():D:\PROJETO SISTEMA ESCRITÓRIO\PROJETO SISTEMA CSL
    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run("app.main:app", host=HOST, port=PORT, reload=False, log_level="info")

if __name__ == "__main__":
    main()
