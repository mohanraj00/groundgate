# groundgate

LLMs propose facts; groundgate decides which ones you can trust.

groundgate is a deterministic admission layer for LLM document extraction. Every extracted
fact is **admitted**, flagged **needs_verification** with the exact place a person should look,
or **rejected** with a stable reason code, and every run produces a receipt anyone can re-verify.

> Status: pre-alpha, under active development. Not yet published to PyPI.

## License

Apache-2.0. See [LICENSE](LICENSE).
