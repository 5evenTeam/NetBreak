# Security policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 2.0.x | Yes |
| 1.0.x | No |

Security fixes are made against the 2.0.x line. If you are running 1.0.0,
upgrade to 2.0.0 before reporting a problem.

## Reporting a vulnerability

Please report security issues privately. Do not open a public issue, and do not
describe the problem in a public discussion, because a working report can put
users at risk before a fix is available.

Use GitHub's private security advisory flow as the first option:

1. Go to [github.com/5evenTeam/NetBreak/security/advisories/new](https://github.com/5evenTeam/NetBreak/security/advisories/new).
2. Describe the issue and how to reproduce it.
3. If you cannot use GitHub advisories, open a minimal issue that asks for a
   private contact channel, without any details of the vulnerability.

Include what you can of the following:

- The version and the engine in use (`netbreak --version` and
  `netbreak --list-engines`).
- The operating system.
- A description of the impact and the steps to reproduce.
- Any suggested fix, if you have one.

We acknowledge reports within 72 hours. We aim to publish a fix, or a decision
about a fix, within a 30-day disclosure window from the acknowledgement. If more
time is needed, we will say so and agree on a new date with you. We are happy to
credit reporters in the release notes unless you would rather stay anonymous.

## Scope

In scope:

- The scanner code in `netbreak/`, including command handling, port and target
  parsing, output writers and the terminal and desktop front ends.
- The native engines under `engines/` and `native/`.
- The packaging layer in `installer/`, including the PyInstaller specs, the
  PowerShell scripts and the Inno Setup script.

Out of scope:

- Findings produced by scanning third-party systems. NetBreak reports what a
  target exposes; those observations are not NetBreak vulnerabilities. Report
  them to the owner of the affected system.
- The behaviour of the networks or devices you scan.
- Vulnerabilities in third-party dependencies that have already been reported
  upstream, unless NetBreak uses them in a way that creates a new problem.

## Authorized use

NetBreak is a reconnaissance tool. It must only be used on systems you own or
have explicit written permission to test. Scanning systems without authorization
is illegal in most jurisdictions, and we cannot treat an unauthorized scan as a
security report about NetBreak.
