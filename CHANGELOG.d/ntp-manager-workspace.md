## NTP Manager — spójny, responsywny interfejs

- Zastąpiono siatkę dwunastu równorzędnych kafelków panelem stanu synchronizacji, czterema kartami parametrów i sekcjami usługi, sieci oraz źródeł czasu.
- Układ nawiązuje do nawigacji modułów zarządzanych i paneli Firewall Managera. Wykorzystuje wspólne komponenty `ModuleHealthCard`, `DataTable` i tokeny motywu WebNAS, bez globalnych zmian wyglądu innych modułów.
- Dodano nawigację z ikonami i oznaczeniem aktywnej sekcji. Zapytania kontenerowe dostosowują interfejs do szerokości okna modułu; tabele przewijają się niezależnie, a treść pozostaje dostępna także w niskim oknie.
- Uporządkowano formularze źródeł, sieci i konfiguracji. Zachowano uprawnienia, operacje edycji i kolejności źródeł, diagnostykę, strefy, historię oraz kopie konfiguracji.
- Dodano czytelne stany ładowania, błędów i pustych list. Nieudany odczyt nie jest przedstawiany jako wyłączona synchronizacja lub zerowa liczba klientów; poprzednie dane są oznaczane przy błędzie odświeżania.
- Odświeżanie nie usuwa niezapisanych ustawień serwera. Nieudane dodanie źródła pozostawia formularz, a operacje mutujące są blokowane na czas wykonywania.
- Dodano testy komponentu, uprawnień, obsługi błędów, prezentacji statusów i kontraktu responsywnego CSS.
