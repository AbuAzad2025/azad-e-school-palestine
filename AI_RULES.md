# Local Development Rules for Azad E-School v2.0

1. **Infrastructure**: Local Windows PostgreSQL (`postgresql-x64-18`) on `localhost:5432/azad_school`. DO NOT attempt Docker or WSL setups.
2. **Running the App**: Simply run `run_local.bat` or `python run.py`.
3. **Database Rules**: Always use the project's atomic `tx()` transaction pattern for DB mutations.
4. **Simplicity First**: Do NOT over-engineer abstractions or change architecture without explicit user instruction.
