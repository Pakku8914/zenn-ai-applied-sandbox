"""python -m docsearch_mcp で起動できるようにする

インストールせずに動かせる経路を残しておくと、配布物の検証（ネットワークに出ない
確認手順）と、利用者側の障害切り分けの両方で助かります。
"""

from .cli import main

raise SystemExit(main())
