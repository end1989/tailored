# Vendored font licences

Every font in this directory is licensed under the [SIL Open Font License 1.1](https://openfontlicense.org/), which permits embedding and redistribution.

These are latin-subset `.woff2` files fetched from the Google Fonts `css2` endpoint by `scripts/vendor_fonts.py` and committed as binaries. There is no build step: the app base64-inlines them at render time so every exported HTML document is standalone.

| Family | Upstream project |
|---|---|
| Inter | https://github.com/rsms/inter |
| IBM Plex Sans | https://github.com/IBM/plex |
| IBM Plex Mono | https://github.com/IBM/plex |
| Public Sans | https://github.com/uswds/public-sans |
| Source Serif 4 | https://github.com/adobe-fonts/source-serif |
| EB Garamond | https://github.com/octaviopardo/EBGaramond12 |
| Source Sans 3 | https://github.com/adobe-fonts/source-sans |
