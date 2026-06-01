# Email-уведомления: отправитель vs получатели

Никакой связи «отправитель = получатель» нет. Apprise `mailto`/`mailtos`
принимает их раздельно:

```
mailtos://USERNAME:APP_PASSWORD@gmail.com?to=team@example.com,boss@example.com&from=docmonitor@gmail.com&name=DocMonitor
```

Что куда:
- `USERNAME:APP_PASSWORD@gmail.com` — учётка, под которой логинимся в SMTP
  (отдельный «бот»-ящик, заведите `docmonitor.bot@gmail.com` или вроде того)
- `to=` — кому слать (через запятую можно несколько адресов)
- `from=` — как подписать письмо
- `name=` — display name отправителя

## Один нюанс именно с Gmail

Gmail не даёт ставить произвольный `From:`, если он не совпадает с
авторизованным ящиком (или с настроенным «Send mail as» alias). Если просто
укажете `from=что-то@gmail.com` ≠ логин — Gmail тихо подменит на адрес логина
(или письмо уедет в спам). Поэтому самый чистый сценарий именно для Gmail:

1. Завести отдельный ящик `docmonitor.notify@gmail.com`
2. У него включить 2FA → создать **App Password** (16 символов, без пробелов)
3. URL уведомления:
   ```
   mailtos://docmonitor.notify:APP_PASSWORD@gmail.com?to=user1@company.com,user2@company.com&from=docmonitor.notify@gmail.com&name=DocMonitor
   ```

`from=` тут совпадает с логином — Gmail доволен, на получателя приходит
«от DocMonitor `<docmonitor.notify@gmail.com>`», даже если получатель
совсем не на Gmail.

## Если ограничения Gmail неудобны

Свободнее работают **транзакционные провайдеры** (бесплатные тиры есть у всех):

- **SendGrid** / **Mailgun** / **Postmark** / **Resend** / **Brevo** — там
  верифицируете домен один раз, потом ставите `from=` любого `*@вашдомен.com`.
- Apprise умеет каждый из них напрямую (есть свои схемы), и SMTP-relay у них
  тоже работает:
  ```
  mailtos://API_KEY@smtp.sendgrid.net?to=...&from=alerts@yourdomain.com
  ```

В коде проекта менять ничего не нужно — это всё чистая правка одной строки
`Notification URL` в Settings → Notifications.
