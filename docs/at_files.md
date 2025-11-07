# 1
请你在 src/codex_mini/ui/repl_input.py 中实现:
当用户输入 @ 之后，如果当前 cwd 是 git 仓库（包括子目录），并且安装有 fd 或者 rg，开始执行补全逻辑：

你捕获 @xxxx 这样一段内容，然后 执行 fd 或者 rg --file 搜索文件和目录，然后给出相对路径的补全。

补全文件后记得末尾插入一个空格，避免后续持续触发。

同时注意需要防抖，避免大量触发 fd 和 rg


# 2
现在不对，比如我输入
@to 的时候，需要提示 src/codex_mini/protocol/tools.py
src/codex_mini/core/tool/tool_registry.py
src/codex_mini/core/tool/
src/codex_mini/core/tool/todo_write_tool.py 等等

然后我再输入一个 d
@tod 的时候，候选项就变成 src/codex_mini/core/tool/todo_write_tool.py

需要这样一个搜索效果，@ 后面的是搜索词


# 3
再解析一下退格呢 @tod 退格成 @to 的时候也要


# 4
仅“@”时也列出一些轻量推荐（比如当前目录）


# 5 (这个实现失败了，尝试了两遍，放弃)
现在补全项是跟随最后一个字符的，有没有办法让它固定在 @ 位置，或者下一行顶格？有没有配置项控制？


# 6
make pyright happy