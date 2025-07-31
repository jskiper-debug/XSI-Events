Pierwsza wersja skryptu Python do pobierania w czasie rzeczywistym informacji przez API XSI Events o połączeniach na numerach dodanych do wirtualnej centralki telefonicznej Broadworks (Cisco). Program zestawia trwałe połączenie typu COMET (HTTP long polling), pobiera w czasie rzeczywistym zdarzenia (informacje o połączeniach telefonicznych) w postaci chunków XML, każdy chunk zapisuje jako osobny plik XML, potwierdza odebrane zdarzenia (ACK), obsługuje tworzenie kanału i subskrypcji, wysyła heartbeat dla podtrzymania kanału gdy nie ma nowych zdarzeń, automatycznie obsługuje błędy, a zakończenie pracy następuje po naciśnięciu ESC. Logi w konsoli są kolorowane (ANSI) dla czytelności.

Do uruchomienia kodu wymagane jest:

instalacja Pythona 3.10+ (python.org](https://www.python.org/downloads/)
instalacja w Python biblioteki requests (pip install requests)
Wersja skompilowana exe zawiera już wymagane biblioteki.

Po uruchomieniu skryptu aby pobierać w czasie rzeczywistym zdarzenia dotyczące połączeń wymagane jest:

posiadanie konta w usłudze wirtualnej centrali telefonicznej opartej na platformie Broadworks (Cisco)
podanie loginu administratora, hasła administratora, identyfikatora Enterprise oraz ID grupy posiadanych w ramach konta
