# Contributing to Dristi

Thank you for considering contributing to **Dristi**! We welcome contributions of all kinds, including bug reports, feature requests, documentation improvements, and code contributions.

---

## Getting Started

To contribute successfully, you must first set up the project on your local machine. Please follow the instructions outlined in the project's [README](README.md) to configure the repository and begin your contributions.

**Prerequisites:**
- Docker and Docker Compose installed
- Git installed
- Basic familiarity with Django and Python

---

## How to Contribute

### 1. Fork the Repository

1. Click the **Fork** button on the top right of this repository.
2. Clone your forked repository:
   ```bash
   git clone https://github.com/{your-username}/dristi-be.git
   cd dristi-be
   ```
3. Set up the upstream remote:
   ```bash
   git remote add upstream https://github.com/pucardotorg/dristi-be.git
   ```

### 2. Check for Existing Issues

Before you start working on a contribution:

1. **Check if an issue exists** for the bug or feature you want to work on in the [Issues](https://github.com/pucardotorg/dristi-be/issues) section.
2. **If no issue exists**, create one first using the appropriate template:
   - **Bug Report** - For reporting bugs or unexpected behavior
   - **Feature Request** - For suggesting new features or capabilities
   - **Enhancement Request** - For improvements to existing functionality
3. **Wait for approval** before starting work on major features or architectural changes.
4. **Comment on the issue** to let others know you're working on it.

### 3. Set Up Your Development Environment

1. Copy the environment file:
   ```bash
   cp .env.example .env
   ```

2. Start the development stack:
   ```bash
   make up
   ```

3. Create a superuser (first time only):
   ```bash
   make superuser
   ```

4. Verify everything is working:
   - API: http://localhost:8000/api/v1/
   - Admin: http://localhost:8000/admin/
   - Swagger UI: http://localhost:8000/api/docs/

### 4. Create a Branch

Always work in a new branch based on `main`. Follow the **Conventional Commits** branch naming convention:

```bash
git checkout -b type/scope-brief-description
```

**Branch name format:** `type/scope-brief-description`

**Type** can be:
- `feat` - A new feature
- `fix` - A bug fix
- `chore` - Tooling, CI, dependencies, maintenance
- `docs` - Documentation only
- `spec` - Specification for agents and fellow devolepers 

**Examples:**
```bash
git checkout -b feat/case-filing-api
git checkout -b fix/auth-token-expiry
git checkout -b chore/update-dependencies
git checkout -b docs/api-documentation
```

### 5. Make and Test Changes

1. **Follow coding standards:**
   - Adhere to the project's Django coding style
   - Follow PEP 8 guidelines
   - Use meaningful variable and function names
   - Add docstrings to functions and classes

2. **Lint your code:**
   ```bash
   make lint
   ```

3. **Format your code:**
   ```bash
   make format
   ```

4. **Run tests:**
   ```bash
   make test
   ```

5. **If you've added new models**, create and run migrations:
   ```bash
   docker compose -f docker/docker-compose.yml exec web python manage.py makemigrations
   make migrate
   ```

6. **Add test cases** for bug fixes and new features:
   - Place tests in the appropriate `tests/` directory
   - Ensure all tests pass before committing

### 6. Verify Application Functionality

Before submitting a pull request:

1. **Start the application:**
   ```bash
   make up
   ```

2. **Test your changes:**
   - [ ] Verify the application runs without errors
   - [ ] Test the specific functionality you modified
   - [ ] Check the admin panel if you modified models
   - [ ] Review the API documentation at http://localhost:8000/api/docs/

3. **Check logs for errors:**
   ```bash
   make logs
   ```

### 7. Commit Changes

Use **Conventional Commits** format for commit messages:

```
type(scope): Brief description

Optional longer description explaining what and why.
```

**Examples:**
```bash
git commit -m "feat(case-filing): Add case document upload API"
git commit -m "fix(auth): Correct token expiry validation"
git commit -m "docs(readme): Update setup instructions"
git commit -m "chore(deps): Upgrade Django to 5.1"
```

**Commit message rules:**
- Use present tense ("Add feature" not "Added feature")
- Use imperative mood ("Move cursor to..." not "Moves cursor to...")
- Keep the first line under 70 characters
- Reference issues: "Closes #123" or "Fixes #456"

### 8. Push and Open a Pull Request

1. **Sync with upstream** (fetch latest changes):
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```

2. **Push your changes:**
   ```bash
   git push origin your-branch-name
   ```

3. **Open a Pull Request:**
   - Go to your fork on GitHub
   - Click "Compare & pull request"
   - Fill out the PR template completely
   - Link the PR to the related issue (use "Closes #issue-number")

4. **PR title format:** Follow Conventional Commits
   ```
   type(scope): Brief summary
   ```
   
   Examples:
   - `feat(collection): Add STT evaluation support`
   - `fix(auth): Correct token validation logic`
   - `docs(api): Enhance endpoint documentation`

---

## PR Review Process

1. **Automated checks** will run:
   - Linting (Ruff)
   - Tests (pytest)
   - Django system checks

2. **Code review:**
   - Maintainers will review your code
   - Address any requested changes
   - Keep the conversation focused and professional

3. **Approval and merge:**
   - Once approved, a maintainer will merge your PR
   - Your contribution will be part of the next release!

---

## Questions?

If you have questions:
- Check the [README](README.md) and [docs/](docs/) first
- Search [existing issues](https://github.com/pucardotorg/dristi-be/issues)
- Ask in [Discussions](https://github.com/pucardotorg/dristi-be/discussions)
- Reach out to maintainers

---

## Code of Conduct

By participating in this project, you agree to:
- Be respectful and inclusive
- Welcome newcomers and help them get started
- Accept constructive criticism gracefully
- Focus on what is best for the community


