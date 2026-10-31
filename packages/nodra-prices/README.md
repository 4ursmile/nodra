# nodra-prices

Plain data package: the model price table that `nodra usage` uses to estimate cost. Nothing is installed into any AI tool.

`prices.json`: `{"prices": [{match, input, output, cache_write?, cache_read?}]}`, USD per 1M tokens. `match` is a regex on the model name, first match wins. Order of use: `~/.nodra/prices.json` (your own file) > the installed `nodra-prices` package > `<root>/packages/nodra-prices/prices.json`.

To change a price edit `prices.json` (or your own `~/.nodra/prices.json`). Bump `version` in `nodra.toml` when you change this package so `nodra update --check` offers it.
