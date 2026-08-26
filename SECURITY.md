# Security Policy

The package performs pure local arithmetic and has no network, filesystem, shell, dynamic-code, credential, or exchange integration surface.

Callers must treat account state, market prices, instrument rules, margin availability, and proposed stops as untrusted inputs and refresh them at the execution boundary. Do not use an accepted intent as a substitute for exchange-side quantity/notional validation, margin checks, protective-order confirmation, reconciliation, or execution monitoring.

Report vulnerabilities privately through https://github.com/FrankFMY. Do not include real account balances, orders, API keys, or strategy data in public reports.
