# Security policy

## Supported versions

Room OS is currently in beta. Security fixes are applied to the latest release
and the `main` branch.

| Version | Supported |
| --- | --- |
| 0.1.x | Yes |
| Older or unreleased builds | No |

## Reporting a vulnerability

Do not open a public issue for vulnerabilities, exposed credentials or reports
that contain biometric or personal data. Use the repository's
[private vulnerability reporting form](https://github.com/diegomoren-lgtm/room-os/security/advisories/new).

Include a concise description, affected version, reproduction steps and expected
impact. Remove API keys, face images, embeddings, camera captures, usernames,
absolute paths and other personal data before submitting evidence.

You should receive an initial response through GitHub within seven days. Please
allow time to investigate and prepare a fix before public disclosure.

## Security model

- Credentials are read from environment variables only.
- Camera, hand, gesture, presence and face processing are local by default.
- Gemini receives an image only after an explicit user request.
- Windows application launches use a fixed allowlist.
- External inputs are bounded and validated at trust boundaries.
- Rich text is escaped before display.
- A future database must use parameterized queries; Room OS currently uses no SQL.

Implementation details are documented in [docs/SECURITY.md](docs/SECURITY.md).
