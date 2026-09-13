# Audyt wykonania 9 — Docker Registry i Proxmox

## Naprawione błędy

- Docker Registry sprawdza wszystkie wystąpienia `Content-Encoding` oraz wszystkie kodowania rozdzielone przecinkami przed odczytem i dekodowaniem treści. Dodatkowy nagłówek `gzip`, `br` lub `deflate` nie omija już kontroli po wcześniejszym `identity`.
- Transport Registry usuwa wszystkie wejściowe warianty `Accept-Encoding` i wysyła dokładnie jeden nagłówek `identity`, zamiast sprzecznych nagłówków różniących się wielkością liter. Poprawne wielokrotne deklaracje `identity` pozostają obsługiwane.
- Registry zamienia błędy limitu długości liczb całkowitych i głębokości JSON na kontrolowany błąd odpowiedzi. Dla niepoprawnego JSON w odpowiedzi HTTP 401 zachowuje status i nagłówek wyzwania uwierzytelnienia.
- Nieskończony timeout połączenia Registry nie trafia do operacji gniazda; stosowana jest skończona wartość zastępcza.
- Wyłączenie weryfikacji certyfikatu Registry nie znosi już minimum TLS 1.2. Jawnie przekazany `SSLContext` nadal jest zachowywany.
- Proxmox odczytuje o jeden bajt więcej niż limit i odrzuca zbyt duże odpowiedzi logowania oraz API, zamiast akceptować poprawny początek uciętego dokumentu JSON. Odpowiedź dokładnie na granicy limitu pozostaje poprawna.
- Proxmox normalizuje niepoprawny JSON, błędne UTF-8, limity parsera oraz niekompletne odpowiedzi HTTP do `ProxmoxApiError` z właściwym etapem. Diagnostyka tych błędów nie zawiera treści otrzymanej odpowiedzi.
- Błąd odczytu opcjonalnej treści błędu Proxmoxa nie maskuje już pierwotnego statusu HTTP. Strumienie odpowiedzi błędów są zamykane także przy wyjątku parsera lub odczytu.
- Logowanie Proxmox odrzuca bilety i tokeny CSRF o błędnym typie, puste lub zawierające znaki niedozwolone w nagłówkach. Nie zamienia już dowolnych obiektów JSON na poświadczenia tekstowe.

## Testy regresyjne

`backend/tests/test_runtime_audit_9.py` dodaje 71 przypadków obejmujących powielone nagłówki, brak odczytu niebezpiecznej treści, limity TLS i timeoutów, rzeczywiste limity parsera JSON, zachowanie statusu HTTP, zamykanie strumieni, granice rozmiaru odpowiedzi i walidację tokenów.

Poprawki dotyczą potwierdzonych przypadków w wymienionych modułach; nie stanowią deklaracji braku wszystkich błędów w całym projekcie.
