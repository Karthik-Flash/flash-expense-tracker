# What Flash stores

Plain words for everyone who uses Flash (5C, D-132). The app shows the same
under Insights > Profile, "What Flash stores", and on the sign-in screen. This is the basis
for the Play Store privacy policy (Phase 6).

- **Only your banks' SMS.** Payments, refunds and transfers your banks send
  you. Never one-time passwords (OTPs), never promotions, never anyone's
  personal messages. The Android app reads SMS on your phone and sends only
  the bank ones; nothing else leaves the phone.
- **Your answers.** Names, categories, labels, and who sent you money.
- **Your email**, to sign in. Your password is kept by the sign-in service
  (Supabase Auth), not by Flash.
- **Where.** On servers in Singapore (Supabase), and only you can see your
  data. The person who runs Flash (the admin) sees each account's email, when
  it joined and last synced, and counts (payments, phones): never your
  payments or messages.
- **Never shared or sold.** Flash does not lend money, score credit or show
  ads.
- **Notifications** for a new payment show its amount and payee on your phone only; they
  are made on the phone from the server's answer to its own upload.
- **Delete everything, any time.** In the app: Insights > Profile, Delete my account.
  It deletes every row of your account on the server, then your login, then
  the copy on your phone (D-131). It cannot be undone.

What is kept outside your account: server logs with the method, route, status
and time of each request (never a body, an amount or a name); only when the
sign-in service could not be reached during a deletion, your login's id until a
retry deletes it; and the owner's weekly database backups (the newest 12, on the
owner's computer, D-157), which hold every account's rows until they age out, about
three months after a deletion.
