# Security & Code Audit Checklist

Используется @analyst/ами (@reviewer, @security, @tester) при аудите кода.
Проверять ВСЕ пункты — не только очевидные.

## 1. XSS / Injection (явное)

- [ ] Все user-controlled строки в `innerHTML`/`outerHTML` проходят через экранирование (`escHtml`, `textContent` и т.п.)
- [ ] Нет прямых `${...}` в template literals, вставляемых в HTML
- [ ] `target="_blank"` links имеют `rel="noopener noreferrer"`
- [ ] CSP не нарушается (inline styles, eval, внешние ресурсы)

## 2. Race Conditions (поведенческое — часто упускают)

- [ ] **Async guard:** каждая `async` функция имеет guard от параллельного вызова:
  ```js
  if (loading) return;
  loading = true;
  try { … } finally { loading = false; }
  ```
- [ ] **setInterval vs fetch:** если `setInterval` вызывает `fetch()`, есть риск что следующий тик сработает до завершения предыдущего
- [ ] **setKey/смена конфига:** при смене API-ключа/настроек — старый in-flight запрос не перетирает новый результат
- [ ] **AbortController:** долгие запросы имеют AbortController, который вызывается при повторном запуске или unmount
- [ ] **Promise race:** если несколько `Promise.all`/`.then` пишут в одно состояние — порядок не гарантирован

## 3. Утечки памяти (Leaks)

- [ ] `setInterval`/`setTimeout`: есть ли `clearInterval`/`clearTimeout` при:
  - [ ] смене конфига/перезапуске
  - [ ] полной очистке состояния
  - [ ] unmount компонента (MutationObserver / disconnect)
- [ ] **Event listeners:** добавленные через `addEventListener` удаляются через `removeEventListener`
- [ ] **MutationObserver/ResizeObserver:** есть `disconnect()` при очистке
- [ ] **Замыкания:** нет захвата больших объектов в колбэках (утечка через closure)

## 4. Асинхронные операции & безопасность

- [ ] **Ошибки сети:** каждый `fetch`/`await` обёрнут в try/catch с user-facing сообщением
- [ ] **Timeout:** нет бесконечно висящих запросов (установлен timeout)
- [ ] **Пагинация без лимита:** если есть постраничная загрузка — есть ли hard limit на количество страниц (чтобы не сделать 10 000 последовательных запросов)
- [ ] **State после ошибки:** после сетевой ошибки состояние корректно сбрасывается, а не остаётся в «загрузка...»

## 5. Безопасность хранилища

- [ ] API-ключи: используются `localStorage`/`sessionStorage` (не cookies без флагов, не URL)
- [ ] Нет логирования sensitive данных (`console.log(apiKey)`)
- [ ] Нет передачи sensitive данных в URL query params

## 6. Качество кода

- [ ] **Мёртвый код:** переменные, функции, CSS-селекторы которые нигде не используются
- [ ] **console.log:** нет отладочного вывода в production
- [ ] **ESLint:** 0 errors (warnings допустимы, но review)
- [ ] **Магические числа:** нет чисел без имени (вынести в const)

## 7. Консистентность документации

- [ ] Структура в README совпадает с реальной файловой структурой
- [ ] Все примеры JSON/YAML валидны
- [ ] Версия в манифестах совпадает с версией в README
- [ ] После рефакторинга (удаление/добавление файлов) вся документация обновлена

---

## Приоритеты

| Severity | Описание |
|----------|----------|
| **CRITICAL** | Race condition с повреждением данных, XSS, утечка API-ключа. Блокирует релиз. |
| **HIGH** | Race без повреждения данных, утечка памяти (timer), бесконечная пагинация. Fix перед релизом. |
| **MEDIUM** | Мёртвый код, отсутствие CI, магические числа. Fix по возможности. |
| **LOW** | style/cosmetic, варнинги ESLint, несущественные неточности в документации. Advisory. |
