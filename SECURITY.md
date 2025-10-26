# 🔒 Security Policy

VebGen takes security seriously. This document outlines our security practices and how to report vulnerabilities.

---

## 🛡️ VebGen's Security Architecture

VebGen is designed with **multiple security layers** to protect your projects and data:

### Built-In Security Features

1. **Sandboxed File Operations**
   - All file operations are restricted to the project root directory
   - Path traversal attempts (`../`, absolute paths) are automatically blocked
   - Symbolic links are validated before access

2. **Command Whitelisting**
   - 50+ safe commands pre-approved (see `command_executor.py`)
   - Dangerous commands (`rm -rf`, `sudo`, etc.) are blocked
   - Shell metacharacters (`;`, `|`, `&`, `` ` ``) are filtered

3. **API Key Encryption**
   - API keys stored in OS-level keyring (Windows Credential Manager, macOS Keychain, Linux Secret Service)
   - Never stored in plain text or committed to Git
   - Encrypted at rest using OS-provided security

4. **No Code Execution Without Review**
   - All LLM-generated code is displayed before execution
   - Manual approval required for sensitive operations
   - Full audit log of all actions

For technical details, see:
- Command Executor Documentation - Whitelist/blocklist implementation
- Secure Storage Documentation - API key encryption
- File System Manager Documentation - Sandbox architecture

---

## Supported Versions

We provide security updates for the following versions:

| Version | Supported          | End of Life  |
| ------- | ------------------ | ------------ |
| 0.3.x   | ✅ Full support    | TBD          |
| 0.2.x   | ✅ Security fixes  | Dec 31, 2025 |
| < 0.2   | ❌ No support      | Oct 1, 2025  |

**Note**: Always use the latest stable version for the best security posture.

---

## 🚨 Reporting a Security Vulnerability

We take all security reports seriously. Thank you for helping us keep VebGen secure!

### How to Report

**For non-sensitive issues:**
- Open a GitHub Security Advisory

**For sensitive vulnerabilities:**
- Email: **vebgenofficial@gmail.com**
- Subject: `[SECURITY] Brief description`
- **Do not report security vulnerabilities through public GitHub issues**

### What to Include

Please provide:
1. **Description** - Clear explanation of the vulnerability
2. **Impact** - What can an attacker achieve?
3. **Steps to Reproduce** - Exact commands/code to trigger the issue
4. **Affected Versions** - Which VebGen versions are vulnerable?
5. **Suggested Fix** (optional) - How would you patch it?
6. **Your Contact Info** - For follow-up questions

**Example Report:**
Subject: [SECURITY] Path traversal in file_system_manager.py

Description: An attacker can bypass sandbox restrictions using Unicode normalization.

Impact: Can read/write files outside project root with specially crafted paths.

Steps to Reproduce:
```text
Start VebGen v0.2.5
Send command: WRITE_FILE path="../../etc/passwd" content="malicious"
File is written outside sandbox
```
Affected Versions: 0.2.0 - 0.2.5

Suggested Fix: Normalize paths with unicodedata.normalize('NFC', path) before validation.

### Our Commitment

- **Response Time**: Within **48 hours** (usually same business day)
- **Status Updates**: Every 7 days until resolved
- **Disclosure Timeline**:
  - **Day 0**: Vulnerability reported
  - **Day 1-7**: Verify and assess severity
  - **Day 7-30**: Develop and test fix
  - **Day 30**: Public disclosure (coordinated with reporter)
- **Credit**: Security researchers are credited in release notes (unless anonymity requested)

### Severity Classification

| Severity | Description | Example |
|----------|-------------|---------|
| **Critical** | Remote code execution, arbitrary file access outside sandbox | Sandbox escape, RCE via LLM injection |
| **High** | Privilege escalation, API key theft | Keyring bypass, command injection |
| **Medium** | Information disclosure, DoS | Memory leaks, path disclosure |
| **Low** | Minor security improvements | Hardening suggestions, best practices |

---

## 🏆 Security Hall of Fame

We recognize security researchers who help keep VebGen secure:

**2025**
- *No reports yet - be the first!*

**Want to be listed?** Report a valid security vulnerability!

---

## 🔐 Security Best Practices for Users

### Protect Your API Keys

1. **Never commit API keys to Git**
   - VebGen stores keys in OS keyring automatically
   - Add `.env` to `.gitignore` if using environment variables

2. **Use read-only API keys when possible**
   - Limit LLM API key permissions to minimum required
   - Use separate keys for development and production

3. **Rotate keys regularly**
   - Change API keys every 90 days
   - Revoke keys immediately if compromised

### Project Safety

1. **Review generated code before running**
   - Inspect commands before clicking "Execute"
   - Check file changes in Git diff

2. **Use version control**
   - Commit your work before running VebGen
   - Roll back easily if something goes wrong

3. **Run in isolated environments**
   - Use virtual machines or containers for untrusted projects
   - Don't run VebGen with root/admin privileges

---

## 📞 Security Contact

- **Email**: vebgenofficial@gmail.com
- **Response Time**: 48 hours
- **PGP Key**: Coming soon

For general questions about VebGen, use GitHub Discussions.

---

## 📜 Security Policy Updates

This policy was last updated: **October 26, 2025**

We review this policy quarterly and update it as needed.
