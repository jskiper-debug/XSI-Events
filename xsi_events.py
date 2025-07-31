import requests
import xml.etree.ElementTree as ET
import threading
import uuid
import time
from datetime import datetime
import os
import base64
import itertools
import sys

if os.name == 'nt':
    import msvcrt
    import ctypes
    kernel32 = ctypes.windll.kernel32
    kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)

CLR_EVENT = '\033[92m'
CLR_RESET = '\033[0m'

LOGIN = ""
PASSWORD = ""
ENTERPRISE_ID = ""
GROUP_ID = ""
PROXY_HOST = ""  # <- Jeśli puste, tylko bezpośrednio, jeśli niepuste: najpierw proxy, potem bezpośrednio

def prompt_if_empty(var, prompt_text):
    if not var.strip():
        return input(prompt_text).strip()
    return var

LOGIN = prompt_if_empty(LOGIN, "Podaj LOGIN do XSI: ")
PASSWORD = prompt_if_empty(PASSWORD, "Podaj PASSWORD do XSI: ")
ENTERPRISE_ID = prompt_if_empty(ENTERPRISE_ID, "Podaj ENTERPRISE_ID: ")
GROUP_ID = prompt_if_empty(GROUP_ID, "Podaj GROUP_ID: ")

BASE_URL = "https://xsi.vpbx.plus.pl/com.broadsoft.xsi-events/v2.0"
ASYNC_BASE_URL = "https://xsi.vpbx.plus.pl/com.broadsoft.async/com.broadsoft.xsi-events/v2.0"

DEFAULT_HEADERS = {
    'Content-Type': 'application/xml',
    'Accept': 'application/xml',
}
authstr = f"{LOGIN}:{PASSWORD}"
authb64 = base64.b64encode(authstr.encode("utf-8")).decode("utf-8")
DEFAULT_HEADERS["Authorization"] = f"Basic {authb64}"

HEARTBEAT_INTERVAL = 30
SUMMARY_LOG = "session_summary.log"
EVENTS_DIR = "XSI Events"
os.makedirs(EVENTS_DIR, exist_ok=True)

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[{ts}] {msg}", flush=True)

def ack_event(session, event_id):
    url = f"{BASE_URL}/channel/eventresponse"
    data = f"""<?xml version="1.0" encoding="UTF-8"?>
<EventResponse xmlns="http://schema.broadsoft.com/xsi">
    <eventID>{event_id if event_id else ''}</eventID>
    <statusCode>200</statusCode>
    <reason>Thats OK</reason>
</EventResponse>
"""
    try:
        resp = session.post(url, data=data, headers=DEFAULT_HEADERS, timeout=5)
        log(f"ACK event_id={event_id}, status={resp.status_code}")
    except Exception as e:
        log(f"ACK exception: {e}")

def get_event_type(xml_string):
    try:
        root = ET.fromstring(xml_string)
        event_data = root.find('.//{http://schema.broadsoft.com/xsi}eventData')
        if event_data is not None:
            event_type = event_data.attrib.get('{http://www.w3.org/2001/XMLSchema-instance}type')
            if event_type:
                return event_type
        return root.tag.split('}', 1)[-1]
    except Exception:
        return "UnknownEvent"

def handle_event(xml_string, session, event_counter):
    event_type = get_event_type(xml_string)
    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    n = next(event_counter)
    safe_event_type = event_type.replace(":", "_").replace("/", "_")
    fname = os.path.join(EVENTS_DIR, f"{now}_{safe_event_type}_{n:03d}.xml")
    with open(fname, "w", encoding="utf-8") as f:
        f.write(xml_string)
    log(f"Zapisano event XML: {fname}")
    try:
        root = ET.fromstring(xml_string)
        event_ids = []
        for event in root.findall('.//{http://schema.broadsoft.com/xsi}Event'):
            event_id_elem = event.find('{http://schema.broadsoft.com/xsi}eventID')
            if event_id_elem is not None and event_id_elem.text not in event_ids:
                event_ids.append(event_id_elem.text)
        for event_id_elem in root.findall('.//{http://schema.broadsoft.com/xsi}eventID'):
            if event_id_elem.text not in event_ids:
                event_ids.append(event_id_elem.text)
        for eid in event_ids:
            ack_event(session, eid)
        if not event_ids:
            log("Brak eventID w evencie, nie wysyłam ACK.")
    except Exception as e:
        log(f"❌ Błąd obsługi/ACK eventu: {e}")

def heartbeat_loop(session, channel_id, stop_event):
    url = f"{BASE_URL}/channel/{channel_id}/heartbeat"
    while not stop_event.is_set():
        time.sleep(HEARTBEAT_INTERVAL)
        req_jsess = session.cookies.get("JSESSIONID", "")
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        print(f"\n[{ts}] >>> HEARTBEAT REQUEST [PUT]", flush=True)
        print(f"  URL: {url}", flush=True)
        print(f"  JSESSIONID: {req_jsess}", flush=True)
        try:
            resp = session.put(url, data="", headers=DEFAULT_HEADERS, timeout=10)
            ts2 = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            resp_jsess = resp.cookies.get("JSESSIONID", req_jsess)
            print(f"\n[{ts2}] <<< HEARTBEAT RESPONSE [HTTP]", flush=True)
            print(f"  STATUS: {resp.status_code}", flush=True)
            print(f"  URL: {resp.url}", flush=True)
            print(f"  JSESSIONID: {resp_jsess}", flush=True)
            body = resp.text.strip()
            if body:
                print(f"  BODY:\n{body}", flush=True)
            log(f"🔄 Heartbeat (status {resp.status_code})")
            if resp.status_code != 200:
                log("🛑 Kanał nie istnieje lub inny błąd – kończę heartbeat i nasłuch chunków.")
                stop_event.set()
                break
        except Exception as e:
            log(f"❌ Błąd Heartbeat: {e}")

def delete_subscription(session, sub_id):
    if sub_id:
        url = f"{BASE_URL}/subscription/{sub_id}"
        try:
            resp = session.delete(url, headers=DEFAULT_HEADERS)
            log(f"❎ Subskrypcja usunięta (status {resp.status_code})")
        except Exception as e:
            log(f"❌ Błąd usuwania subskrypcji: {e}")

def delete_channel(session, ch_id):
    if ch_id:
        url = f"{BASE_URL}/channel/{ch_id}/delete"
        try:
            resp = session.delete(url, headers=DEFAULT_HEADERS)
            log(f"❎ Kanał usunięty (status {resp.status_code})")
        except Exception as e:
            log(f"❌ Błąd usuwania kanału: {e}")

def create_subscription(session, channel_set_id, sub_id_out, stop_event):
    url_sub = f"{BASE_URL}/enterprise/{ENTERPRISE_ID}/group/{GROUP_ID}"
    data_sub = f"""
    <Subscription xmlns="http://schema.broadsoft.com/xsi">
      <event>Advanced Call</event>
      <expires>3600</expires>
      <channelSetId>{channel_set_id}</channelSetId>
      <applicationId>CommPilotApplication</applicationId>
    </Subscription>
    """
    jsess = session.cookies.get("JSESSIONID", "")
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"\n[{ts}] >>> SUBSCRIPTION REQUEST [POST]", flush=True)
    print(f"  URL: {url_sub}", flush=True)
    print(f"  JSESSIONID: {jsess}", flush=True)
    print(f"  BODY:\n{data_sub.strip()}\n", flush=True)
    try:
        resp = session.post(url_sub, data=data_sub.strip(), headers=DEFAULT_HEADERS, timeout=10)
    except Exception as e:
        log(f"❌ Nie udało się połączyć z XSI przy tworzeniu subskrypcji.\nBłąd: {str(e)}")
        stop_event.set()
        return

    ts2 = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"\n[{ts2}] <<< SUBSCRIPTION RESPONSE", flush=True)
    print(f"  STATUS: {resp.status_code}", flush=True)
    print(f"  URL: {resp.url}", flush=True)
    print(f"  JSESSIONID: {jsess}", flush=True)
    print(f"  BODY:\n{resp.text.strip()}\n", flush=True)
    try:
        root = ET.fromstring(resp.text)
        sub_id_elem = root.find('{http://schema.broadsoft.com/xsi}subscriptionId')
        sub_id = sub_id_elem.text if sub_id_elem is not None else None
        expires_elem = root.find('{http://schema.broadsoft.com/xsi}expires')
        if expires_elem is not None:
            expires_val = int(expires_elem.text)
            hours = expires_val // 3600
            minutes = (expires_val % 3600) // 60
            seconds = expires_val % 60
            log(f"✅ Subskrypcja utworzona: {sub_id} (ważna przez {hours}h {minutes}min {seconds}s)")
        else:
            log(f"✅ Subskrypcja utworzona: {sub_id}")
        if sub_id:
            sub_id_out.append(sub_id)
    except Exception as e:
        log(f"❌ Błąd parsowania subskrypcji: {e}")
        stop_event.set()

def wait_for_esc(stop_event):
    if os.name == 'nt':
        while not stop_event.is_set():
            if msvcrt.kbhit():
                key = msvcrt.getch()
                if key == b'\x1b':  # ESC
                    log("Naciśnięto ESC – kanał oraz subskrypcja zostaną zamknięte...")
                    stop_event.set()
                    break

def main():
    print(f"\nZdarzenia będą zapisywane do katalogu: {os.path.abspath(EVENTS_DIR)}\nAby zakończyć program, naciśnij ESC.\n", flush=True)

    session = requests.Session()

    if PROXY_HOST.strip():
        # Najpierw spróbuj z proxy
        session.proxies = {
            'http':  f'http://{PROXY_HOST}',
            'https': f'http://{PROXY_HOST}'
        }
        log(f"Używam proxy: {PROXY_HOST}")

        try:
            connect_session = session
            session_channel_set_id = str(uuid.uuid4())
            log(f"Używany channelSetId: {session_channel_set_id}")

            url_channel = f"{ASYNC_BASE_URL}/channel"
            data_channel = f"""
            <Channel xmlns="http://schema.broadsoft.com/xsi">
              <channelSetId>{session_channel_set_id}</channelSetId>
              <priority>1</priority>
              <weight>50</weight>
              <expires>3600</expires>
              <applicationId>CommPilotApplication</applicationId>
            </Channel>
            """
            jsess = session.cookies.get("JSESSIONID", "")
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"\n[{ts}] >>> CHANNEL REQUEST [POST]", flush=True)
            print(f"  URL: {url_channel}", flush=True)
            print(f"  JSESSIONID: {jsess}", flush=True)
            print(f"  BODY:\n{data_channel.strip()}\n", flush=True)

            resp = session.post(url_channel, data=data_channel.strip(), headers=DEFAULT_HEADERS, timeout=60, stream=True)
        except Exception as e:
            log(f"❌ Nie udało się połączyć przez proxy: {PROXY_HOST}. Spróbuję połączyć bezpośrednio (bez proxy)...\nBłąd: {str(e)}")
            # Spróbuj bez proxy
            session = requests.Session()
            session.proxies = {}
            log("Proxy nie zostanie użyte (połączenie bezpośrednie).")

            try:
                connect_session = session
                session_channel_set_id = str(uuid.uuid4())
                log(f"Używany channelSetId: {session_channel_set_id}")

                url_channel = f"{ASYNC_BASE_URL}/channel"
                data_channel = f"""
                <Channel xmlns="http://schema.broadsoft.com/xsi">
                  <channelSetId>{session_channel_set_id}</channelSetId>
                  <priority>1</priority>
                  <weight>50</weight>
                  <expires>3600</expires>
                  <applicationId>CommPilotApplication</applicationId>
                </Channel>
                """
                jsess = session.cookies.get("JSESSIONID", "")
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(f"\n[{ts}] >>> CHANNEL REQUEST [POST]", flush=True)
                print(f"  URL: {url_channel}", flush=True)
                print(f"  JSESSIONID: {jsess}", flush=True)
                print(f"  BODY:\n{data_channel.strip()}\n", flush=True)

                resp = session.post(url_channel, data=data_channel.strip(), headers=DEFAULT_HEADERS, timeout=60, stream=True)
            except Exception as e2:
                log(f"❌ Nie udało się połączyć z XSI bezpośrednio ani przez proxy!\nBłąd: {str(e2)}")
                sys.exit(1)
    else:
        session.proxies = {}
        log("Proxy nie zostanie użyte (połączenie bezpośrednie).")

        try:
            connect_session = session
            session_channel_set_id = str(uuid.uuid4())
            log(f"Używany channelSetId: {session_channel_set_id}")

            url_channel = f"{ASYNC_BASE_URL}/channel"
            data_channel = f"""
            <Channel xmlns="http://schema.broadsoft.com/xsi">
              <channelSetId>{session_channel_set_id}</channelSetId>
              <priority>1</priority>
              <weight>50</weight>
              <expires>3600</expires>
              <applicationId>CommPilotApplication</applicationId>
            </Channel>
            """
            jsess = session.cookies.get("JSESSIONID", "")
            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"\n[{ts}] >>> CHANNEL REQUEST [POST]", flush=True)
            print(f"  URL: {url_channel}", flush=True)
            print(f"  JSESSIONID: {jsess}", flush=True)
            print(f"  BODY:\n{data_channel.strip()}\n", flush=True)

            resp = session.post(url_channel, data=data_channel.strip(), headers=DEFAULT_HEADERS, timeout=60, stream=True)
        except Exception as e:
            log(f"❌ Nie udało się połączyć z XSI. Sprawdź adres/proxy/internet.\nBłąd: {str(e)}")
            sys.exit(1)

    ts2 = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    jsess2 = connect_session.cookies.get("JSESSIONID", "")
    print(f"\n[{ts2}] <<< CHANNEL RESPONSE", flush=True)
    print(f"  STATUS: {resp.status_code}", flush=True)
    print(f"  URL: {resp.url}", flush=True)
    print(f"  JSESSIONID: {jsess2}", flush=True)
    print(f"  BODY:\n[chunked - reading...]\n", flush=True)

    buffer = ''
    channel_id = None
    sub_id_out = []
    stop_event = threading.Event()
    heartbeat_thr = None
    sub_thr = None
    event_counter = itertools.count(1)

    # Załóż subskrypcję OD RAZU
    sub_thr = threading.Thread(target=create_subscription, args=(connect_session, session_channel_set_id, sub_id_out, stop_event), daemon=True)
    sub_thr.start()

    esc_thread = threading.Thread(target=wait_for_esc, args=(stop_event,), daemon=True)
    esc_thread.start()

    try:
        for chunk in resp.iter_content(chunk_size=4096):
            if stop_event.is_set():
                break
            buffer += chunk.decode('utf-8', errors='ignore')
            while True:
                start = buffer.find('<?xml')
                if start == -1:
                    break
                next_start = buffer.find('<?xml', start + 5)
                if next_start == -1:
                    xml_event = buffer[start:]
                    buffer = ''
                else:
                    xml_event = buffer[start:next_start]
                    buffer = buffer[next_start:]
                ts3 = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(f"{CLR_EVENT}\n[{ts3}] <<< EVENT (from /channel stream)\n  BODY:\n{xml_event.strip()}{CLR_RESET}\n", flush=True)

                try:
                    root = ET.fromstring(xml_event)
                    if root.tag.endswith('Channel'):
                        expires_elem = root.find('{http://schema.broadsoft.com/xsi}expires')
                        channel_id_elem = root.find('{http://schema.broadsoft.com/xsi}channelId')
                        channel_id = channel_id_elem.text if channel_id_elem is not None else None
                        expires_val = int(expires_elem.text) if expires_elem is not None else 0
                        hours = expires_val // 3600
                        minutes = (expires_val % 3600) // 60
                        seconds = expires_val % 60
                        log(f"✅ Kanał założony: {channel_id} (ważny przez {hours}h {minutes}min {seconds}s)")
                        if not heartbeat_thr and channel_id:
                            heartbeat_thr = threading.Thread(target=heartbeat_loop, args=(connect_session, channel_id, stop_event), daemon=True)
                            heartbeat_thr.start()
                    elif root.tag.endswith('Subscription'):
                        expires_elem = root.find('{http://schema.broadsoft.com/xsi}expires')
                        sub_id_elem = root.find('{http://schema.broadsoft.com/xsi}subscriptionId')
                        if expires_elem is not None:
                            expires_val = int(expires_elem.text)
                            hours = expires_val // 3600
                            minutes = (expires_val % 3600) // 60
                            seconds = expires_val % 60
                            log(f"✅ Subskrypcja utworzona: {sub_id_elem.text if sub_id_elem is not None else None} (ważna przez {hours}h {minutes}min {seconds}s)")
                        else:
                            log(f"✅ Subskrypcja utworzona: {sub_id_elem.text if sub_id_elem is not None else None}")
                        if sub_id_elem is not None:
                            if sub_id_elem.text not in sub_id_out:
                                sub_id_out.append(sub_id_elem.text)
                except Exception:
                    pass

                handle_event(xml_event.strip(), connect_session, event_counter)

        if buffer.strip():
            event_type = get_event_type(buffer)
            now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            n = next(event_counter)
            safe_event_type = event_type.replace(":", "_").replace("/", "_")
            fname = os.path.join(EVENTS_DIR, f"{now}_{safe_event_type}_{n:03d}.xml")
            with open(fname, "w", encoding="utf-8") as f:
                f.write(buffer)
            log(f"Zapisano niekompletny XML chunk: {fname}")

    except Exception as ex:
        log(f"❌ Błąd główny: {ex}")

    stop_event.set()
    if heartbeat_thr: heartbeat_thr.join(timeout=2)
    if sub_thr: sub_thr.join(timeout=2)
    if sub_id_out:
        delete_subscription(connect_session, sub_id_out[0])
    if channel_id:
        delete_channel(connect_session, channel_id)
    log("✅ Zakończono.")

if __name__ == "__main__":
    main()
