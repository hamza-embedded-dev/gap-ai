# Contributing

- `main` is protected: work on a branch and open a pull request.
- Branch names: `<role>/<short-topic>`, e.g. `b1/api-skeleton`, `w2/demo-login`, `d1/audio-upload`.
- Commit messages: `type: short description` (`feat`, `fix`, `docs`, `test`, `chore`).
- Every pull request is read by at least one other person. "It works" is not enough: know why it works.
- `docs/api-contract.md` and `ai/schema.json` are the only authority for payloads. Do not invent endpoints or fields.
  Changes to them need review from the integrator and the code reviewer.
- Never commit API keys, tokens, Wi-Fi passwords or real participant data. Use `.env` (ignored) and `.env.example`.
- Do not paste secrets or real user data into AI tools.
- Check the license of every library, font, icon or snippet before adding it.
- `main` must always run. After the feature freeze (19 Oct 2026) only bug, security, test and docs changes are accepted.
