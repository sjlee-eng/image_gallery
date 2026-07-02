# CLAUDE.md

Guidance for AI assistants (Claude Code and others) working in this repository.

## What this repository actually is

Despite the name `image_gallery`, this repository currently contains **no
application code** — no gallery app, no framework, no build system, no
package manifest, no tests, no CI configuration. It consists solely of four
AI-generated PNG images (dogs wearing chef hats, 1024x1024) committed
directly to the repository root:

- `1.png`, `2.png`, `3.png`, `4.png`
- `1.png.png`, `2.png.png`, `3.png.png`, `4.png.png`

The `*.png.png` files are **byte-for-byte duplicates** of the correspondingly
numbered `*.png` files (verified via checksum) — they appear to be an
upload mistake (the extension was added twice) rather than distinct assets.

There is no source directory, no `package.json`/`requirements.txt`/etc., no
README, and no documented purpose for these images beyond being raw uploads.

## Implications for future work

Because there is no existing codebase, standard conventions below (build
commands, test commands, folder structure, coding style) **do not apply
yet** — there is nothing to build, run, lint, or test. Do not assume a
framework, language, or architecture that isn't present.

If the intent is to actually build an image gallery application here:
- Ask the user what stack they want (this repo gives no signal — no
  manifest or config files exist to infer one from).
- Treat the four PNGs as sample/seed content, not as anything load-bearing.
- The duplicate `*.png.png` files are very likely unwanted uploads; confirm
  with the user before deleting them, since removing files is a destructive
  action.

## Working conventions for this repo today

- Before assuming any dev workflow (install, build, test, lint) exists,
  check for the relevant manifest/config file first — as of this writing,
  none exist.
- If you add real application code, update this file with the actual
  structure, commands, and conventions you introduce, so it reflects
  reality rather than a generic template.
- Keep this document in sync with the repository's actual state; do not
  describe workflows, directories, or tooling that don't exist.
