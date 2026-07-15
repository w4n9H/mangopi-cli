#!/usr/bin/env bash
###############################################################################
# __          _
# \ \   _ __ | |__
#  \ \ | '_ \| '_ \
#  / / | | | | |_) |
# /_/  |_| |_|_.__/
#
# [memo] Your notes, in your filesystem, queryable by you.
#
# 极简的 CLI 笔记系统,从 xwmx/nb (https://github.com/xwmx/nb) 提炼:
#   - 纯文本文件 + .index 软 ID
#   - 嵌套 folders(局部 .index, 路径式 ID 3.1.2)
#   - todo / tasks(checkbox 解析)
#   - 系统级 grep 全文检索(rg > ag > ack > grep)
#   - Git 自动同步
#   - 单库 ~/.nb/home/(不做多 notebook / bookmark / 加密 / 插件 / browse)
#
# 用法:
#   memo init                              初始化
#   memo add "标题" [--content "..."]      创建笔记
#   memo ls [--folder X] [--type md]       列出
#   memo show <id|title>                   查看
#   memo search "关键词" [...]             搜索(支持 AND/OR/NOT/tag)
#   memo edit <id>                         编辑
#   memo delete <id> [--archive|--force]   删除/归档
#   memo sync                              Git 同步
#   memo folders add|mv|ls|list|show       文件夹
#   memo todo "事项" [-t 子项]              todo
#   memo do|undone <id>                    切换 todo 状态
#   memo --help                            帮助
#
# Target Bash: >= 3.2 (兼容 macOS 自带版本)
# License: MIT
###############################################################################

# ---------- 严格模式 ----------
# 注: 不用 set -e(errexit), 跟 ((expr)) / 命令组不友好。
# 也不用 set -u(nounset), 在大函数库里与 "${@}" / "${1}" 等组合时
# 在某些 Bash 版本上会触发 "@: unbound variable"。改用显式
# ${VAR:-} 防御 + set -o pipefail + 显式错误检查。
set -o pipefail
set -o noglob
IFS=$'\n\t'

# ---------- 版本 ----------
_VERSION="0.2.0"

# ---------- 路径常量 ----------
_HOME="${HOME:-/tmp}"
_NB_DIR_DEFAULT="${_HOME}/.nb"
_NB_DIR="${NB_DIR:-${_NB_DIR_DEFAULT}}"
_NB_NOTEBOOK_NAME="home"
_NB_DEFAULT_EXTENSION="${NB_DEFAULT_EXTENSION:-md}"

# ---------- 当前脚本的元信息 ----------
_ME="$(basename "${0}")"
_MY_DIR="$(cd "$(dirname "${0}")" && pwd)"

# ---------- 子命令注册 ----------
_SUBCOMMANDS=(
  add
  archive
  count
  delete
  do
  done
  edit
  folders
  help
  init
  ls
  list
  mv
  move
  ns
  pin
  rename
  rm
  search
  show
  sync
  task
  tasks
  todo
  todos
  unpin
  undone
  version
)

# ============================================================================
# 工具函数
# ============================================================================

# _command_exists()
# 用法: _command_exists <name>
# 返回: 0 找到, 1 找不到
_command_exists() {
  hash "${1}" 2>/dev/null
}

# _contains()
# 用法: _contains <query> <list-item>...
# 返回: 0 包含, 1 不包含
_contains() {
  local _query="${1:-}"
  shift
  if [[ -z "${_query}" ]]
  then
    return 1
  fi
  local __element
  for __element in "${@}"
  do
    if [[ "${__element}" == "${_query}" ]]
    then
      return 0
    fi
  done
  return 1
}

# _sed_i()
# 用法: _sed_i <sed-arg>...
# 跨平台 sed -i(macOS BSD sed 需要 -i '' ,Linux GNU sed 不需要)
_sed_i() {
  if sed --help >/dev/null 2>&1
  then
    sed -i "${@}"
  else
    sed -i '' "${@}"
  fi
}

# _lower()
# 用法: _lower <string>
# 返回: 小写后的字符串
# Bash 3.2 不支持 ${VAR,,} 语法, 用 tr 代替
_lower() {
  printf "%s" "${1:-}" | tr '[:upper:]' '[:lower:]'
}

# _tput()
# 用法: _tput <capability> [args...]
# 跨平台 tput(空 TERM 时降级)
_tput() {
  if [[ -n "${TERM:-}" ]] && [[ "${TERM}" != "dumb" ]]
  then
    tput "${@}" 2>/dev/null || printf ""
  else
    printf ""
  fi
}

# _color_enabled()
# 用法: _color_enabled
# 返回: 0 启用颜色, 1 禁用
_COLOR_ENABLED="${NO_COLOR:+0}"
_COLOR_ENABLED="${_COLOR_ENABLED:-1}"
color_enabled() {
  ((_COLOR_ENABLED))
}

# _color_primary()
# 用法: _color_primary <text>
_color_primary() {
  if color_enabled
  then
    printf "%s%s%s" "$(_tput setaf 6)" "${1:-}" "$(_tput sgr0)"
  else
    printf "%s" "${1:-}"
  fi
}

# _color_dim()
# 用法: _color_dim <text>
_color_dim() {
  if color_enabled
  then
    printf "%s%s%s" "$(_tput setaf 8)" "${1:-}" "$(_tput sgr0)"
  else
    printf "%s" "${1:-}"
  fi
}

# _color_warn()
_color_warn() {
  if color_enabled
  then
    printf "%s%s%s" "$(_tput setaf 1)" "${1:-}" "$(_tput sgr0)"
  else
    printf "%s" "${1:-}"
  fi
}

# _color_ok()
_color_ok() {
  if color_enabled
  then
    printf "%s%s%s" "$(_tput setaf 2)" "${1:-}" "$(_tput sgr0)"
  else
    printf "%s" "${1:-}"
  fi
}

# _format_size()
# 用法: _format_size <bytes>
_format_size() {
  local _size="${1:-0}"
  if ((_size < 1024))
  then
    printf "%d B" "${_size}"
  elif ((_size < 1024 * 1024))
  then
    printf "%.1fK" "$(echo "${_size} / 1024" | bc -l)"
  else
    printf "%.1fM" "$(echo "${_size} / 1024 / 1024" | bc -l)"
  fi
}

# _format_date()
# 用法: _format_date <epoch>
_format_date() {
  date -d "@${1}" +"%Y-%m-%d" 2>/dev/null || date -r "${1}" +"%Y-%m-%d" 2>/dev/null || printf "?"
}

# _exit_1()
_exit_1() {
  printf "%s %s\n" "$(_color_warn "!")" "${*}" >&2
  exit 1
}

# _warn()
_warn() {
  printf "%s %s\n" "$(_color_warn "!")" "${*}" >&2
}

# _info()
_info() {
  printf "%s %s\n" "$(_color_ok "✓")" "${*}"
}

# _trim()  去掉首尾空白
_trim() {
  local _v="${1:-}"
  _v="${_v#"${_v%%[![:space:]]*}"}"
  _v="${_v%"${_v##*[![:space:]]}"}"
  printf "%s" "${_v}"
}

# ============================================================================
# 路径
# ============================================================================

# _notebook_path()
# 当前 notebook 路径(单库,只支持 home)
_notebook_path() {
  printf "%s/%s" "${_NB_DIR}" "${_NB_NOTEBOOK_NAME}"
}

# _resolve_folder_path()
# 用法: _resolve_folder_path <relative_path> [<base>]
# 例: _resolve_folder_path "工作日志"            → /home/x/.nb/home/工作日志
#     _resolve_folder_path "工作日志/2025"       → /home/x/.nb/home/工作日志/2025
#     _resolve_folder_path "工作日志/2025" ".."  → 相对 base 的路径
# 返回: 绝对路径字符串(写到 stdout)
_resolve_folder_path() {
  local _rel="${1:-}"
  local _base="${2:-$(printf "%s/%s" "${_NB_DIR}" "${_NB_NOTEBOOK_NAME}")}"
  # 去掉尾斜杠
  _rel="${_rel%/}"
  if [[ -z "${_rel}" ]]
  then
    printf "%s" "${_base}"
  else
    printf "%s/%s" "${_base}" "${_rel}"
  fi
}

# _ensure_index()
# 用法: _ensure_index <folder_path>
# 确保 .index 存在
_ensure_index() {
  local _folder="${1}"
  if [[ ! -e "${_folder}/.index" ]]
  then
    : > "${_folder}/.index"
  fi
}

# ============================================================================
# 文件名解析(.index 软 ID)
# ============================================================================

# _parse_filename()
# 用法: _parse_filename <filename>
# 例: _parse_filename "1-项目.md"            → id=1 title="项目" ext="md"
#     _parse_filename "3.1-章节.md"          → id=3.1 title="章节" ext="md"
#     _parse_filename "工作日志.1-项目.md"   → id=工作日志.1 title="项目" ext="md"
#     _parse_filename "README.md"            → id="" title="README" ext="md"
# 返回: 写到 stdout 形如 "id\ttitle\text"
_parse_filename() {
  local _name="${1}"
  # 匹配: ID 部分(纯数字路径 或 含文件夹名.数字路径) + 可选 -title + .ext
  # ID 不能含 -，因为 - 是 ID 和 title 的分隔
  # 扩展名最后一段不能含 - (限制 .md .org 等)
  if [[ "${_name}" =~ ^([0-9]+(\.[0-9]+)*|[^.-]+(\.[0-9]+)+)(-(.+))?\.(md|org|tex|adoc|txt|enc|bookmark\.md)$ ]]
  then
    printf "%s\t%s\t%s" "${BASH_REMATCH[1]}" "${BASH_REMATCH[5]:-}" "${BASH_REMATCH[6]}"
    return 0
  fi
  # 普通文件名(没 ID,像 README.md)
  if [[ "${_name}" =~ ^(.+)\.(md|org|tex|adoc|txt|enc|bookmark\.md)$ ]]
  then
    printf "\t%s\t%s" "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}"
    return 0
  fi
  return 1
}

# _build_filename()
# 用法: _build_filename <id> <title> <ext>
_build_filename() {
  local _id="${1:-}"
  local _title="${2:-}"
  local _ext="${3:-${_NB_DEFAULT_EXTENSION}}"
  # 标题清洗:去掉路径分隔符和不可见字符
  local _safe="${_title}"
  _safe="${_safe//\//-}"
  _safe="${_safe//$'\n'/-}"
  _safe="${_safe//$'\r'/-}"
  _safe="${_safe//$'\t'/-}"
  if [[ -n "${_id}" ]] && [[ -n "${_safe}" ]]
  then
    printf "%s-%s.%s" "${_id}" "${_safe}" "${_ext}"
  elif [[ -n "${_id}" ]]
  then
    printf "%s.%s" "${_id}" "${_ext}"
  else
    printf "%s.%s" "${_safe}" "${_ext}"
  fi
}

# ============================================================================
# .index 维护
# ============================================================================

# _read_index()
# 用法: _read_index <index_path>
# 返回: 多行 "id\ttitle" 到 stdout
# 接受格式: "1-title" / "3.1-title" / "1" / "1\ttitle" / "1\tfirst title"
_read_index() {
  local _idx="${1}"
  if [[ ! -f "${_idx}" ]]
  then
    return 0
  fi
  local _line
  while IFS= read -r _line
  do
    _line="$(_trim "${_line}")"
    [[ -z "${_line}" ]] && continue
    # 格式 1: "1-title"
    if [[ "${_line}" =~ ^([0-9]+(\.[0-9]+)*)(-(.*))?$ ]]
    then
      printf "%s\t%s\n" "${BASH_REMATCH[1]}" "${BASH_REMATCH[4]:-}"
    elif [[ "${_line}" == $'\t'* ]]
    then
      # tab 分隔(防 _index_add 写错)
      local _first="${_line%%$'\t'*}"
      local _rest="${_line#*$'\t'}"
      printf "%s\t%s\n" "${_first}" "${_rest}"
    fi
  done < "${_idx}"
}

# _write_index()
# 用法: _write_index <index_path> <entries...>
# entries 形如 "id\ttitle"
_write_index() {
  local _idx="${1}"
  shift
  local _tmp
  _tmp="$(mktemp)"
  local _entry _id _title
  for _entry in "${@}"
  do
    _id="${_entry%%$'\t'*}"
    _title="${_entry#*$'\t'}"
    if [[ -n "${_title}" ]]
    then
      printf "%s-%s\n" "${_id}" "${_title}" >> "${_tmp}"
    else
      printf "%s\n" "${_id}" >> "${_tmp}"
    fi
  done
  mv "${_tmp}" "${_idx}"
}

# _next_id()
# 用法: _next_id <index_path> [<prefix>]
# 返回: 下一个可用 ID(数字)
# 例: _next_index_id .        → 4
#     _next_index_id . "3."   → 3.2(在 3 之下找下一个子 ID)
_next_id() {
  local _idx="${1}"
  local _prefix="${2:-}"
  local _max=0
  local _line _id_part
  while IFS= read -r _line
  do
    _line="$(_trim "${_line}")"
    [[ -z "${_line}" ]] && continue
    # 提取 ID 部分(去掉 -title)
    _id_part="${_line%%-*}"
    # 应用 prefix 过滤
    if [[ -n "${_prefix}" ]]
    then
      if [[ "${_id_part}" != "${_prefix}"* ]]
      then
        continue
      fi
      # 取 prefix 之后的部分
      local _rest="${_id_part#${_prefix}}"
      # 必须是空或 .数字
      if [[ -z "${_rest}" ]] || [[ "${_rest}" =~ ^\.[0-9]+$ ]]
      then
        if [[ -z "${_rest}" ]]
        then
          _max=0  # prefix 本身就是 ID
        else
          local _n="${_rest#.}"
          if ((_n > _max))
          then
            _max="${_n}"
          fi
        fi
      fi
    else
      # 无 prefix:找根 ID 的最大值(忽略 .X 后缀)
      local _root="${_id_part%%.*}"
      # 必须是纯数字(跳过如 "工作日志.1" 这种以中文开头的 ID)
      if [[ "${_root}" =~ ^[0-9]+$ ]] && ((_root > _max))
      then
        _max="${_root}"
      fi
    fi
  done < "${_idx}"
  if [[ -n "${_prefix}" ]]
  then
    printf "%s%d" "${_prefix}" "$((_max + 1))"
  else
    printf "%d" "$((_max + 1))"
  fi
}

# _next_id_in_folder()
# 用法: _next_id_in_folder <index_path> <prefix>
# 返回: 该 prefix 下的下一个子数字(如 "工作日志." → 2)
_next_id_in_folder() {
  local _idx="${1}"
  local _prefix="${2}"
  local _max=0
  local _line _id_part
  while IFS= read -r _line
  do
    _line="$(_trim "${_line}")"
    [[ -z "${_line}" ]] && continue
    _id_part="${_line%%-*}"
    if [[ "${_id_part}" == "${_prefix}"* ]]
    then
      local _rest="${_id_part#${_prefix}}"
      if [[ "${_rest}" =~ ^[0-9]+$ ]] && ((_rest > _max))
      then
        _max="${_rest}"
      fi
    fi
  done < "${_idx}"
  printf "%d" "$((_max + 1))"
}

# _index_add()
# 用法: _index_add <index_path> <id> <title>
_index_add() {
  local _idx="${1}"
  local _id="${2}"
  local _title="${3:-}"
  if [[ -n "${_title}" ]]
  then
    printf "%s-%s\n" "${_id}" "${_title}" >> "${_idx}"
  else
    printf "%s\n" "${_id}" >> "${_idx}"
  fi
}

# _index_remove()
# 用法: _index_remove <index_path> <id>
_index_remove() {
  local _idx="${1}"
  local _id="${2}"
  local _tmp
  _tmp="$(mktemp)"
  local _line _cur_id
  while IFS= read -r _line
  do
    _line="$(_trim "${_line}")"
    [[ -z "${_line}" ]] && continue
    _cur_id="${_line%%-*}"
    if [[ "${_cur_id}" != "${_id}" ]]
    then
      printf "%s\n" "${_line}" >> "${_tmp}"
    fi
  done < "${_idx}"
  mv "${_tmp}" "${_idx}"
}

# ============================================================================
# 文件类型检测
# ============================================================================

# _detect_type()
# 用法: _detect_type <filename>
# 返回: md / org / tex / txt / bookmark / enc / unknown
_detect_type() {
  local _name="$(_lower "${1:-}")"
  case "${_name}" in
    *.bookmark.md) printf "bookmark" ;;
    *.enc)         printf "enc" ;;
    *.md)          printf "md" ;;
    *.org)         printf "org" ;;
    *.tex)         printf "tex" ;;
    *.adoc)        printf "adoc" ;;
    *.txt)         printf "txt" ;;
    *)             printf "unknown" ;;
  esac
}

# _indicator()
# 用法: _indicator <type> [state]
# 返回: 单字符 emoji
_indicator() {
  local _type="${1:-unknown}"
  local _state="${2:-}"
  case "${_type}:${_state}" in
    bookmark:*)    printf "🔖" ;;
    enc:*)         printf "🔒" ;;
    md:done)       printf "✅" ;;
    md:open)       printf "☐ " ;;
    md:*)          printf "📝" ;;
    org:*)         printf "📓" ;;
    tex:*)         printf "📐" ;;
    adoc:*)        printf "📃" ;;
    txt:*)         printf "📃" ;;
    *)             printf "  " ;;
  esac
}

# _is_todo_done()
# 用法: _is_todo_done <file>
# 返回: 0 含 [x] 或 [X](全完成),1 含未完成,2 无 checkbox
_is_todo_state() {
  local _f="${1}"
  if [[ ! -f "${_f}" ]]
  then
    printf "none"
    return
  fi
  local _has_open=0 _has_done=0
  local _line
  while IFS= read -r _line
  do
    if [[ "${_line}" =~ ^[[:space:]]*-[[:space:]]\[[xX]\][[:space:]] ]]
    then
      _has_done=1
    elif [[ "${_line}" =~ ^[[:space:]]*-[[:space:]]\[[[:space:]]\][[:space:]] ]] || [[ "${_line}" =~ ^[[:space:]]*-[[:space:]]\[[[:space:]]\][[:space:]]*$ ]]
    then
      _has_open=1
    fi
  done < "${_f}"
  if ((_has_done)) && ((_has_open))
  then
    printf "mixed"
  elif ((_has_done))
  then
    printf "done"
  elif ((_has_open))
  then
    printf "open"
  else
    printf "none"
  fi
}

# ============================================================================
# Git 操作
# ============================================================================

# _is_git_repo()
_is_git_repo() {
  [[ -d "${1}/.git" ]]
}

# _git_init()
_git_init() {
  local _dir="${1}"
  if _is_git_repo "${_dir}"
  then
    return 0
  fi
  if ! _command_exists git
  then
    return 1
  fi
  git -C "${_dir}" init -b master >/dev/null 2>&1 || git -C "${_dir}" init >/dev/null 2>&1
  if [[ ! -f "${_dir}/.gitignore" ]]
  then
    printf ".cache/\n*.swp\n.DS_Store\n" > "${_dir}/.gitignore"
  fi
  git -C "${_dir}" add . >/dev/null 2>&1 || true
  local _env
  _env=$(env \
    GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-memo}" \
    GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-memo@local}" \
    GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-memo}" \
    GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-memo@local}" \
    git -C "${_dir}" commit -m "Initial commit" 2>&1) || true
}

# _git_checkpoint()
# 用法: _git_checkpoint <folder> <message>
# 返回: 0 commit 了, 1 跳过
_git_checkpoint() {
  local _dir="${1}"
  local _msg="${2:-checkpoint}"
  if ! _is_git_repo "${_dir}"
  then
    return 1
  fi
  if ! _command_exists git
  then
    return 1
  fi
  git -C "${_dir}" add . >/dev/null 2>&1 || true
  # 没 staged 改动就跳过
  if git -C "${_dir}" diff --cached --quiet 2>/dev/null
  then
    return 1
  fi
  env \
    GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-memo}" \
    GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-memo@local}" \
    GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-memo}" \
    GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-memo@local}" \
    git -C "${_dir}" commit -m "${_msg}" >/dev/null 2>&1
  return 0
}

# _git_sync()
# 用法: _git_sync <folder>
_git_sync() {
  local _dir="${1}"
  if ! _is_git_repo "${_dir}"
  then
    _exit_1 "${_dir} 不是 Git 仓库,先 memo init"
  fi
  if ! _command_exists git
  then
    _exit_1 "git 未安装"
  fi
  local _has_remote=0
  if git -C "${_dir}" remote -v 2>/dev/null | grep -q .
  then
    _has_remote=1
  fi
  # 1. pull
  if ((_has_remote))
  then
    git -C "${_dir}" pull --rebase --autostash 2>/dev/null || _warn "pull 失败(可忽略)"
  fi
  # 2. commit 本地改动
  _git_checkpoint "${_dir}" "sync" || true
  # 3. push
  if ((_has_remote))
  then
    if ! git -C "${_dir}" push 2>/dev/null
    then
      _warn "push 失败(可能没配 upstream)"
    fi
  fi
  _info "同步完成: ${_dir}"
}

# ============================================================================
# 编辑器
# ============================================================================

__set_editor() {
  if [[ -n "${EDITOR:-}" ]]
  then
    return 0
  fi
  if [[ -n "${VISUAL:-}" ]]
  then
    EDITOR="${VISUAL}"
    return 0
  fi
  # 探测顺序: vim 先(优先), 其次是 GUI 编辑器, 最后 nano/vi 兑底
  local _editors=(vim nvim vi code subl micro mate macdown nano pico emacs)
  local _e
  for _e in "${_editors[@]}"
  do
    if _command_exists "${_e}"
    then
      EDITOR="${_e}"
      return 0
    fi
  done
  _exit_1 "找不到编辑器,设置 \$EDITOR"
}
__set_editor

# _edit_in_editor()
# 用法: _edit_in_editor <initial_content>
# 返回: 编辑后内容(写到 stdout)
_edit_in_editor() {
  local _initial="${1:-}"
  local _tmp
  # macOS BSD mktemp 需要 -t prefix.XXX(XXX 是大写 X)
  _tmp="$(mktemp -t memo-edit.XXXXXXXX 2>/dev/null || mktemp -t memo-edit)"
  # mktemp 后缀可选: 加 .md 让 vim 启用 markdown 高亮
  [[ "${_tmp}" != *.md ]] && mv "${_tmp}" "${_tmp}.md" && _tmp="${_tmp}.md"
  printf "%s" "${_initial}" > "${_tmp}"

  # 确保 vim 从 /dev/tty 读, 避免非交互式环境下的 "Output is not to a terminal" 警告
  if [[ -t 0 ]] && [[ -t 1 ]]
  then
    # 标准 TTY 模式
    "${EDITOR}" "${_tmp}"
  elif [[ -e /dev/tty ]] && [[ -r /dev/tty ]] && [[ -w /dev/tty ]]
  then
    # 非 TTY 但 /dev/tty 可用 (例如管道重定向后)
    "${EDITOR}" "${_tmp}" < /dev/tty > /dev/tty 2>&1
  else
    # 最后兑底: 纯 cat (不打开编辑器, 警告用户)
    printf "警告: 无可用 TTY, 跳过编辑。请手动提供 --content 参数。\n" >&2
  fi

  cat "${_tmp}"
  rm -f "${_tmp}"
}

# ============================================================================
# 文件夹 / 路径工具
# ============================================================================

# _is_under_notebook()
_is_under_notebook() {
  local _p="${1}"
  local _nb
  _nb="$(_notebook_path)"
  case "${_p}" in
    "${_nb}"|"${_nb}/"*) return 0 ;;
    *) return 1 ;;
  esac
}

# _is_valid_folder()
_is_valid_folder() {
  local _p="${1}"
  [[ -d "${_p}" ]] || return 1
  # 必须是 notebook 内的目录
  _is_under_notebook "${_p}" || return 1
  # 不能是 notebook 本身
  local _nb
  _nb="$(_notebook_path)"
  [[ "${_p}" != "${_nb}" ]] || return 1
  return 0
}

# _folder_create()
_folder_create() {
  local _rel="${1:-}"
  local _abs
  _abs="$(_resolve_folder_path "${_rel}")"
  if [[ -d "${_abs}" ]]
  then
    _warn "文件夹已存在: ${_rel}"
    return 0
  fi
  mkdir -p "${_abs}" || _exit_1 "创建文件夹失败: ${_abs}"
  _ensure_index "${_abs}"
  _info "创建文件夹: ${_rel}"
}

# _list_files()
# 用法: _list_files <folder> [recursive]
# 返回: 文件路径列表到 stdout(按名字排序,过滤隐藏 + .git + .enc)
_list_files() {
  local _folder="${1}"
  local _recursive="${2:-0}"
  if [[ ! -d "${_folder}" ]]
  then
    return 0
  fi
  # -not -path 排除 .git 目录里的所有东西
  if ((_recursive))
  then
    find "${_folder}" \
      -type f \
      -not -name '.*' \
      -not -path '*/.git/*' \
      -not -path '*.git' \
      -not -name '*.enc' 2>/dev/null | sort
  else
    find "${_folder}" -maxdepth 1 \
      -type f \
      -not -name '.*' \
      -not -name '*.enc' 2>/dev/null | sort
  fi
}

# _list_subdirs()
_list_subdirs() {
  local _folder="${1}"
  [[ -d "${_folder}" ]] || return 0
  find "${_folder}" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort
}

# ============================================================================
# 命令: init
# ============================================================================

init() {
  local _with_git=1
  while ((${#}))
  do
    case "${1:-}" in
      --no-git) _with_git=0; shift;;
      *) _exit_1 "init 未知参数: ${1}" ;;
    esac
    shift
  done

  local _nb
  _nb="$(_notebook_path)"
  mkdir -p "${_nb}"
  _ensure_index "${_nb}"

  if [[ ! -f "${_nb}/README.md" ]]
  then
    cat > "${_nb}/README.md" <<'EOF'
# memo notebook

这是 memo 的默认 notebook。

## 用法
```bash
memo add "标题" --content "..."
memo ls
memo show 1
memo search "关键词"
```

## 目录结构
- `.index` - 软 ID 维护
- `N-标题.md` - 普通笔记
- `N-标题.bookmark.md` - 书签
- `N-标题/` - 文件夹(可嵌套)

## 配置文件
- `~/.memorc` - 可选,见 memo --help
EOF
  fi

  if [[ ! -f "${_HOME}/.memorc.example" ]]
  then
    cat > "${_HOME}/.memorc.example" <<'EOF'
# memo 配置文件示例(放到 ~/.memorc)
# export NB_DIR="$HOME/notes"           # 笔记根目录
# export NB_DEFAULT_EXTENSION="md"      # 默认扩展名
# export EDITOR="vim"                   # 编辑器
EOF
  fi

  if ((_with_git))
  then
    _git_init "${_nb}"
  fi

  _info "初始化完成: ${_nb}"
  printf "%s\n" "  下一步:"
  printf "    %s\n" "$(printf "%s add \"我的第一篇笔记\" --content \"hello memo\"" "${_ME}")"
  printf "    %s\n" "$(printf "%s ls" "${_ME}")"
}

# ============================================================================
# 命令: add
# ============================================================================

add() {
  local _title="" _content="" _ext="" _folder="" _edit=0 _force=0 _no_git=0
  local _type=""
  while ((${#}))
  do
    case "${1:-}" in
      -c|--content)
        _content="${2:-}"
        shift 2 || _exit_1 "--content 需要值"
        ;;
      -e|--edit)        _edit=1; shift;;
      -f|--folder)
        _folder="${2:-}"
        shift 2 || _exit_1 "--folder 需要值"
        ;;
      -t|--type)
        _type="${2:-}"
        shift 2 || _exit_1 "--type 需要值"
        ;;
      --no-git)         _no_git=1; shift;;
      --force|-F)       _force=1; shift;;
      -h|--help)        _help_add; return 0 ;;
      --) shift; break ;;
      -*) _exit_1 "add 未知选项: ${1}" ;;
      *)
        if [[ -z "${_title}" ]]
        then
          _title="${1}"
        else
          _exit_1 "add 只能接受一个标题参数"
        fi
        shift
        ;;
    esac
  done

  [[ -z "${_type}" ]] && _type="${_NB_DEFAULT_EXTENSION}"

  # 决定目标文件夹
  local _target
  _target="$(_resolve_folder_path "${_folder}")"
  if [[ ! -d "${_target}" ]]
  then
    if ((_force)) || _prompt_yes "文件夹 ${_folder:-.} 不存在,创建吗?"
    then
      _folder_create "${_folder}"
    else
      _exit_1 "已取消"
    fi
  fi
  _ensure_index "${_target}"

  # 决定 ID
  local _idx="${_target}/.index"
  local _id
  if [[ -n "${_folder}" ]]
  then
    # 文件夹内:取该文件夹下"工作日志.N"最大值 + 1
    local _n
    _n=$(_next_id_in_folder "${_idx}" "${_folder}.")
    _id="${_folder}.${_n}"
  else
    _id="$(_next_id "${_idx}")"
  fi

  # 决定标题
  if [[ -z "${_title}" ]]
  then
    printf "%s " "标题:"
    read -r _title
  fi
  [[ -z "${_title}" ]] && _title=""

  # 决定内容
  local _body=""
  if [[ -n "${_content}" ]]
  then
    _body="${_content}"
  elif ((_edit)) || ([[ -z "${_title}" ]] && [[ -z "${_content}" ]])
  then
    _body="$(_edit_in_editor "")"
  fi

  # 拼最终内容
  local _final=""
  if [[ -n "${_title}" ]]
  then
    _final="# ${_title}"
    [[ -n "${_body}" ]] && _final="${_final}

${_body}"
  else
    _final="${_body}"
  fi

  # 写文件
  local _fname
  _fname="$(_build_filename "${_id}" "${_title}" "${_type}")"
  local _fpath="${_target}/${_fname}"

  if [[ -e "${_fpath}" ]]
  then
    _exit_1 "文件已存在: ${_fpath}"
  fi

  printf "%s" "${_final}" > "${_fpath}" || _exit_1 "写文件失败: ${_fpath}"

  # 更新 .index
  _index_add "${_idx}" "${_id}" "${_title}"

  # Git(checkpoint 失败不视为 add 失败)
  if ! ((_no_git))
  then
    _git_checkpoint "${_target}" "add: ${_title:-${_fname}}" || true
  fi

  printf "%s 创建笔记 %s %s\n" "$(_color_ok "✓")" "$(_color_primary "${_id}")" "${_title:-${_fname}}"
  printf "  %s\n" "$(_color_dim "${_fpath}")"
}

_help_add() {
  cat <<EOF
${_ME} add - 创建笔记

用法:
  ${_ME} add "<标题>" [--content "<内容>"] [--edit] [--folder "<路径>"]
                    [--type <ext>] [--force] [--no-git]

选项:
  -c, --content TEXT  直接给内容,不开编辑器
  -e, --edit          保存前用 \$EDITOR 编辑
  -f, --folder PATH   放进文件夹(自动创建)
  -t, --type EXT      文件扩展名(默认 md)
  -F, --force         文件夹不存在时直接创建,不询问
      --no-git        不自动 commit
EOF
}

# ============================================================================
# 命令: ls / list
# ============================================================================

list() {
  local _folder="" _type="" _limit=20 _pinned=0 _all=0 _show_done=0
  while ((${#}))
  do
    case "${1:-}" in
      -a|--all)          _all=1; shift;;
      -n|--limit)
        _limit="${2:-20}"
        shift 2
        ;;
      -f|--folder)
        _folder="${2:-}"
        shift 2
        ;;
      -t|--type)
        _type="${2:-}"
        shift 2
        ;;
      -p|--pinned)       _pinned=1; shift;;
      --done)            _show_done=1; shift;;
      -h|--help)         _help_list; return 0 ;;
      --) shift; break ;;
      -*) _exit_1 "ls 未知选项: ${1}" ;;
      *) shift ;;
    esac
  done

  local _target
  _target="$(_resolve_folder_path "${_folder}")"
  if [[ ! -d "${_target}" ]]
  then
    _exit_1 "文件夹不存在: ${_folder:-.}"
  fi

  local _files
  _files="$(_list_files "${_target}" 0)"
  [[ -z "${_files}" ]] && { _warn "空文件夹"; return 0; }

  local _count=0
  local _max_id_len=1
  local _f _parsed _id _title _ext _type_actual _tstate _ind
  # 先算最大 ID 宽度
  while IFS= read -r _f
  do
    _parsed="$(_parse_filename "$(basename "${_f}")")" || continue
    _id="${_parsed%%$'\t'*}"
    [[ -z "${_id}" ]] && continue
    if (( ${#_id} > _max_id_len ))
    then
      _max_id_len=${#_id}
    fi
  done <<< "${_files}"

  printf "%s\n" "$(_color_primary "📓 ${_NB_NOTEBOOK_NAME}$([[ -n "${_folder}" ]] && printf \"/${_folder}\")${_type:+ [${_type}]}")"
  while IFS= read -r _f
  do
    _parsed="$(_parse_filename "$(basename "${_f}")")" || continue
    _id="${_parsed%%$'\t'*}"
    local _rest="${_parsed#*$'\t'}"
    _title="${_rest%%$'\t'*}"
    _ext="${_rest##*$'\t'}"
    _type_actual="$(_detect_type "$(basename "${_f}")")"
    _tstate="$(_is_todo_state "${_f}")"

    # 过滤
    if [[ -n "${_type}" ]] && [[ "${_type}" != "${_type_actual}" ]]
    then
      continue
    fi
    if ! ((_all)) && ((_count >= _limit))
    then
      break
    fi

    if [[ "${_tstate}" == "open" ]] || [[ "${_tstate}" == "mixed" ]]
    then
      _ind="$(_indicator "${_type_actual}" "open")"
    elif [[ "${_tstate}" == "done" ]]
    then
      _ind="$(_indicator "${_type_actual}" "done")"
    else
      _ind="$(_indicator "${_type_actual}")"
    fi

    local _id_padded
    printf -v _id_padded "%-${_max_id_len}s" "${_id}"
    local _size _mtime _date
    # 拿 mtime epoch: GNU 用 stat -c %Y, BSD/macOS 用 stat -f %m
    _mtime=$(stat -c '%Y' "${_f}" 2>/dev/null) || _mtime=$(stat -f '%m' "${_f}" 2>/dev/null)
    _size=$(stat -c '%s' "${_f}" 2>/dev/null) || _size=$(stat -f '%z' "${_f}" 2>/dev/null)
    : "${_mtime:=0}" "${_size:=0}"
    _date="$(_format_date "${_mtime}")"

    printf "  %s %s  %s  %s  %s\n" \
      "$(_color_primary "${_id_padded}")" \
      "${_ind}" \
      "${_title:-$(basename "${_f}")}" \
      "$(_color_dim "$(_format_size "${_size}")")" \
      "$(_color_dim "${_date}")"
    _count=$((_count + 1))
  done <<< "${_files}"
  printf "%s\n" "$(_color_dim "共 ${_count} 条")"
}

_help_list() {
  cat <<EOF
${_ME} ls - 列出笔记

用法:
  ${_ME} ls [--folder PATH] [--type EXT] [--limit N] [--all] [--pinned]

选项:
  -a, --all         显示全部(否则按 limit 截断)
  -n, --limit N     显示条数(默认 20)
  -f, --folder PATH 限定文件夹
  -t, --type EXT    按类型过滤 (md/org/txt/bookmark)
  -p, --pinned      只显示置顶
EOF
}

# ============================================================================
# 命令: show
# ============================================================================

show() {
  local _selector="" _pager=0
  while ((${#}))
  do
    case "${1:-}" in
      -p|--pager) _pager=1; shift;;
      -h|--help)  _help_show; return 0 ;;
      --) shift; break ;;
      -*) _exit_1 "show 未知选项: ${1}" ;;
      *)  _selector="${1}"; shift ;;
    esac
  done
  [[ -z "${_selector}" ]] && _exit_1 "用法: memo show <id|title>"

  local _fpath
  _fpath="$(_resolve_selector "${_selector}")" || _exit_1 "找不到笔记: ${_selector}"
  [[ ! -f "${_fpath}" ]] && _exit_1 "找不到笔记: ${_selector}"

  printf "%s %s\n" "$(_color_dim "───")" "$(_color_dim "$(basename "${_fpath}")")"
  if ((_pager))
  then
    "${PAGER:-less}" "${_fpath}" 2>/dev/null || cat "${_fpath}"
  else
    cat "${_fpath}"
  fi
}

_help_show() {
  cat <<EOF
${_ME} show - 查看笔记

用法:
  ${_ME} show <id|title> [--pager]

选项:
  -p, -- pager 用 \$PAGER(默认 less)分页
EOF
}

# _resolve_selector()
# 用法: _resolve_selector <selector>
# 返回: 文件绝对路径(写到 stdout)
_resolve_selector() {
  local _sel="${1}"
  local _nb
  _nb="$(_notebook_path)"

  # 1. 纯数字 ID(可能含 .)
  if [[ "${_sel}" =~ ^[0-9]+(\.[0-9]+)*$ ]]
  then
    local _id="${_sel}"
    local _root_id="${_id%%.*}"
    local _rel=""
    if [[ "${_id}" == *.* ]]
    then
      _rel="${_id%.*}"
    fi
    local _folder
    _folder="$(_resolve_folder_path "${_rel}")"
    local _f
    while IFS= read -r _f
    do
      local _parsed
      _parsed="$(_parse_filename "$(basename "${_f}")")" || continue
      local _cur_id="${_parsed%%$'\t'*}"
      if [[ "${_cur_id}" == "${_id}" ]]
      then
        printf "%s" "${_f}"
        return 0
      fi
    done < <(_list_files "${_folder}" 0)
    return 1
  fi

  # 2. 带文件夹前缀的 ID(工作日志.1)
  if [[ "${_sel}" =~ ^(.+)\.([0-9]+)$ ]]
  then
    local _folder_rel="${BASH_REMATCH[1]}"
    local _id="${BASH_REMATCH[2]}"
    local _folder
    _folder="$(_resolve_folder_path "${_folder_rel}")"
    if [[ ! -d "${_folder}" ]]
    then
      return 1
    fi
    local _f
    while IFS= read -r _f
    do
      local _parsed
      _parsed="$(_parse_filename "$(basename "${_f}")")" || continue
      local _cur_id="${_parsed%%$'\t'*}"
      # cur_id 应该是 "${_folder_rel}.${_id}"
      if [[ "${_cur_id}" == "${_folder_rel}.${_id}" ]]
      then
        printf "%s" "${_f}"
        return 0
      fi
    done < <(_list_files "${_folder}" 0)
    return 1
  fi

  # 3. 完整文件名(可能含路径)
  local _candidate="${_nb}/${_sel}"
  if [[ -f "${_candidate}" ]]
  then
    printf "%s" "${_candidate}"
    return 0
  fi

  # 4. 标题模糊匹配(在 notebook 范围内递归)
  local _f
  while IFS= read -r _f
  do
    local _parsed
    _parsed="$(_parse_filename "$(basename "${_f}")")" || continue
    local _rest="${_parsed#*$'\t'}"
    local _title="${_rest%%$'\t'*}"
    local _title_lc _sel_lc
    _title_lc="$(_lower "${_title}")"
    _sel_lc="$(_lower "${_sel}")"
    if [[ "${_title_lc}" == *"${_sel_lc}"* ]]
    then
      printf "%s" "${_f}"
      return 0
    fi
  done < <(_list_files "${_nb}" 1)
  return 1
}

# ============================================================================
# 命令: search
# ============================================================================

search() {
  local _and_q=() _or_q=() _not_q=() _tags=()
  local _type="" _limit=50 _color=1 _list_only=0 _use_regex=0
  local _explicit_query=0

  while ((${#}))
  do
    case "${1:-}" in
      --and)
        _and_q+=("${2:-}")
        _explicit_query=1
        shift 2 || _exit_1 "--and 需要值"
        ;;
      --or)
        # 收集 --or 后面的所有非 flag 参数, 全部当 OR 元素
        shift
        _explicit_query=1
        while ((${#})) && [[ "${1:-}" != -* ]]
        do
          _or_q+=("${1}")
          shift
        done
        ((${#_or_q[@]} == 0)) && _exit_1 "--or 需要值"
        ;;
      --not)
        _not_q+=("${2:-}")
        _explicit_query=1
        shift 2 || _exit_1 "--not 需要值"
        ;;
      --tag)
        _tags+=("${2:-#}")
        _explicit_query=1
        shift 2 || _exit_1 "--tag 需要值"
        ;;
      -t|--type)
        _type="${2:-}"
        shift 2
        ;;
      -l|--list) _list_only=1; shift;;
      --limit|-n)
        _limit="${2:-50}"
        shift 2
        ;;
      --no-color) _color=0; shift;;
      -h|--help)  _help_search; return 0 ;;
      --regex)    _use_regex=1; shift;;
      --) shift; break ;;
      -*) _exit_1 "search 未知选项: ${1}" ;;
      *)
        _and_q+=("${1}")
        _explicit_query=1
        shift
        ;;
    esac
  done

  if ! ((_explicit_query))
  then
    _exit_1 "用法: memo search <keyword> ..."
  fi

  # 选 grep 工具
  local _util=""
  if _command_exists rg
  then
    _util="rg"
  elif _command_exists ag
  then
    _util="ag"
  elif _command_exists ack
  then
    _util="ack"
  elif _command_exists grep
  then
    _util="grep"
  else
    _exit_1 "找不到搜索工具(需要 rg/ag/ack/grep)"
  fi
  if [[ -n "${MEMO_SEARCH_TOOL:-${NB_SEARCH_TOOL:-}}" ]]
  then
    _util="${MEMO_SEARCH_TOOL:-${NB_SEARCH_TOOL}}"
  fi

  local _nb
  _nb="$(_notebook_path)"

  # 1. 拼 AND/OR 模式
  # 默认走 fixed-string (-F), 只有 --regex 才走正则
  # 这样 SQL / 含 .* 等元字符的关键词不会出错
  local _and_pat=""
  if ((${#_and_q[@]} > 0))
  then
    if ((_use_regex))
    then
      # regex 模式: 直接拼接, 不转义 (用户应该知道自己在用 regex)
      _and_pat="$(_join_regex ".*" "${_and_q[@]}")"
    else
      _and_pat="$(_join_regex ".*" "${_and_q[@]}")"
    fi
  fi

  local _or_pat=""
  if ((${#_or_q[@]} > 0))
  then
    if ((_use_regex))
    then
      _or_pat="$(_join_regex "|" "${_or_q[@]}")"
    else
      _or_pat="$(_join_regex "|" "${_or_q[@]}")"
    fi
  fi

  local _tag_pat=""
  if ((${#_tags[@]} > 0))
  then
    _tag_pat="(^|[[:space:]])#[[:alnum:]_/-]+"
  fi

  local _exclude_pat=""
  if ((${#_not_q[@]} > 0))
  then
    if ((_use_regex))
    then
      _exclude_pat="$(_join_regex "|" "${_not_q[@]}")"
    else
      _exclude_pat="$(_join_regex "|" "${_not_q[@]}")"
    fi
  fi

  # 2. 拼最终搜索模式
  local _final_pat=""
  if [[ -n "${_tag_pat}" ]]
  then
    _final_pat="${_tag_pat}"
  elif [[ -n "${_and_pat}" ]] && [[ -n "${_or_pat}" ]]
  then
    # AND+OR 混合: OR 匹配 + .* + AND 首项
    if ((_use_regex))
    then
      _final_pat="(${_or_pat}).*${_and_pat#.*}"
    else
      # fixed-string 模式不支持单趟 AND+OR, 此处仅限 OR 生效
      # (需多趟匹配, 此版本简化为 OR)
      _final_pat="${_or_pat}"
    fi
  elif [[ -n "${_and_pat}" ]]
  then
    _final_pat="${_and_pat}"
  elif [[ -n "${_or_pat}" ]]
  then
    _final_pat="${_or_pat}"
  fi

  # 2.5 fixed-string AND 需多趟匹配 (每个 AND 词独立 grep 然后取交集)
  local _and_post=()
  if ! ((_use_regex)) && ((${#_and_q[@]} > 1)) && [[ -z "${_tag_pat}" ]] && [[ -z "${_or_pat}" ]]
  then
    _and_post=("${_and_q[@]:1}")
    _final_pat="${_and_q[0]}"
  fi

  # 3. 文件列表(过滤 .enc 和隐藏)
  local _files
  _files="$(_list_files "${_nb}" 1)"
  if [[ -n "${_type}" ]]
  then
    _files="$(printf "%s\n" "${_files}" | grep -E "\.${_type}$" || true)"
  fi
  [[ -z "${_files}" ]] && { _warn "无文件可搜"; return 0; }

  # 4. 主搜
  # 用 while-read 循环代替 xargs, 避免 macOS BSD xargs 不支持 -d '\n' 的问题
  local _raw_hits=""
  if [[ -n "${_final_pat}" ]]
  then
    while IFS= read -r _f
    do
      [[ -z "${_f}" ]] && continue
      [[ -f "${_f}" ]] || continue
      local _hits
      case "${_util}" in
        rg)
          local _rg_args=(--hidden --iglob '!.git' --ignore-case --color never --line-number --no-heading --with-filename)
          if ! ((_use_regex))
          then
            _rg_args+=(--fixed-strings)
          fi
          if ! ((_use_regex)) && [[ "${_final_pat}" == *"|"* ]]
          then
            local _pp _OR_ARGS=()
            IFS='|' read -r -a _pp <<< "${_final_pat}"
            _OR_ARGS=(-e "${_pp[0]}")
            local _i
            for _i in "${_pp[@]:1}"
            do
              _OR_ARGS+=(-e "${_i}")
            done
            _hits=$(rg "${_rg_args[@]}" "${_OR_ARGS[@]}" "${_f}" 2>/dev/null || true)
          else
            _hits=$(rg "${_rg_args[@]}" "${_final_pat}" "${_f}" 2>/dev/null || true)
          fi
          ;;
        ag)
          local _ag_args=(--filename --hidden --ignore ".git" --ignore-case --noheading --nocolor)
          if ! ((_use_regex))
          then
            _ag_args+=(--literal)
          fi
          if ! ((_use_regex)) && [[ "${_final_pat}" == *"|"* ]]
          then
            local _pp _OR_ARGS=()
            IFS='|' read -r -a _pp <<< "${_final_pat}"
            _OR_ARGS=("${_pp[0]}")
            local _i
            for _i in "${_pp[@]:1}"
            do
              _OR_ARGS+=(--literal "${_i}")
            done
            _hits=$(ag "${_ag_args[@]}" "${_OR_ARGS[@]}" "${_f}" 2>/dev/null || true)
          else
            _hits=$(ag "${_ag_args[@]}" "${_final_pat}" "${_f}" 2>/dev/null || true)
          fi
          ;;
        ack)
          local _ack_args=(--ignore-case --noheading --with-filename --nocolor)
          if ! ((_use_regex))
          then
            _ack_args+=(-Q)
          fi
          if ! ((_use_regex)) && [[ "${_final_pat}" == *"|"* ]]
          then
            local _pp _OR_ARGS=()
            IFS='|' read -r -a _pp <<< "${_final_pat}"
            _OR_ARGS=("${_pp[0]}")
            local _i
            for _i in "${_pp[@]:1}"
            do
              _OR_ARGS+=("${_i}")
            done
            _hits=$(ack "${_ack_args[@]}" "${_OR_ARGS[@]}" "${_f}" 2>/dev/null || true)
          else
            _hits=$(ack "${_ack_args[@]}" "${_final_pat}" "${_f}" 2>/dev/null || true)
          fi
          ;;
        grep)
          # BSD + GNU 都兼容的 grep 调用
          if ((_use_regex))
          then
            _hits=$(grep -E -H -n "${_final_pat}" "${_f}" 2>/dev/null || true)
          else
            if [[ "${_final_pat}" == *"|"* ]]
            then
              local _pp _OR_ARGS=()
              IFS='|' read -r -a _pp <<< "${_final_pat}"
              _OR_ARGS=(-e "${_pp[0]}")
              local _i
              for _i in "${_pp[@]:1}"
              do
                _OR_ARGS+=(-e "${_i}")
              done
              _hits=$(grep -F -H -n "${_OR_ARGS[@]}" "${_f}" 2>/dev/null || true)
            else
              _hits=$(grep -F -H -n "${_final_pat}" "${_f}" 2>/dev/null || true)
            fi
          fi
          ;;
      esac
      # 把 grep 输出的 "path:line:content" 转成 "path\tline||content"
      # - 用 \t 拼 path 和剩余部分(因为 path 可能含 ":")
      # - line 和 content 之间用 "||" 分隔(因为 content 几乎不可能含 "||")
      # - 从右往左找第一个全数字段作为行号(避免 path 末尾也含数字 + 误判)
      if [[ -n "${_hits}" ]]
      then
        _hits="$(printf "%s\n" "${_hits}" | awk -F: '
          {
            n = NF
            # 从右往左找第一个全数字的字段(行号)
            line = ""
            ci = 0
            for (i = n; i >= 1; i--) {
              if ($i ~ /^[0-9]+$/) { line = $i; ci = i + 1; break }
            }
            if (line == "" || ci > n) next
            # content = ci 到 n, 用 : 拼接
            content = $ci
            for (i = ci + 1; i <= n; i++) content = content ":" $i
            # path = $1 到 ci-2, 用 : 拼接
            path = $1
            for (i = 2; i <= ci-2; i++) path = path ":" $i
            printf "%s\t%s||%s\n", path, line, content
          }')"
        [[ -n "${_hits}" ]] && _raw_hits="${_raw_hits}${_hits}"$'\n'
      fi
    done <<< "${_files}"
    _raw_hits="${_raw_hits%$'\n'}"
  fi

  # 4.5 fixed-string AND 二次过滤 (只有第一个词走 rg/ag/grep, 后续词在结果上逐个 grep)
  if ((${#_and_post[@]} > 0)) && [[ -n "${_raw_hits}" ]]
  then
    local _post_hits=""
    local _hit_line
    while IFS=$'\t' read -r _pf _rest
    do
      [[ -z "${_pf}" ]] && continue
      local _all_match=1
      local _pq
      for _pq in "${_and_post[@]}"
      do
        if ! grep -Fq "${_pq}" "${_pf}" 2>/dev/null
        then
          _all_match=0
          break
        fi
      done
      if ((_all_match))
      then
        _post_hits="${_post_hits}${_pf}"$'\t'"${_rest}"$'\n'
      fi
    done <<< "${_raw_hits}"
    _raw_hits="${_post_hits%$'\n'}"
  fi

  # 5. NOT 过滤 (逐行过滤, 只丢包含 _exclude_pat 的那些行)
  # NOT 的 _exclude_pat 可能是 OR 形式 "basic|foo", 固定字串 OR 需要拆为 -e
  if [[ -n "${_exclude_pat}" ]]
  then
    # 构建 NOT grep 参数
    local _excl_grep_args=()
    if ((_use_regex))
    then
      _excl_grep_args+=(-E -v)
      _excl_grep_args+=(-e "${_exclude_pat}")
    else
      _excl_grep_args+=(-F -v)
      if [[ "${_exclude_pat}" == *"|"* ]]
      then
        local _pp
        IFS='|' read -r -a _pp <<< "${_exclude_pat}"
        _excl_grep_args+=(-e "${_pp[0]}")
        local _i
        for _i in "${_pp[@]:1}"
        do
          _excl_grep_args+=(-e "${_i}")
        done
      else
        _excl_grep_args+=(-e "${_exclude_pat}")
      fi
    fi

    # 对每条 _raw_hits 行用 grep -v 过滤 (丢包含 NOT 模式的行)
    local _post_hits=""
    local _hit_line
    while IFS= read -r _hit_line
    do
      [[ -z "${_hit_line}" ]] && continue
      # _hit_line 格式: /path/file\tline||content (用 tab 和 || 分隔)
      local _pf="${_hit_line%%	*}"
      local _rest="${_hit_line#*	}"
      local _pn="${_rest%%||*}"
      local _pc="${_rest#*||}"
      # 检查该行是否包含 NOT 模式
      local _has_excluded
      if ((_use_regex))
      then
        if printf "%s" "${_pc}" | grep -E -q "${_exclude_pat}" 2>/dev/null
        then
          _has_excluded=1
        else
          _has_excluded=0
        fi
      else
        if printf "%s" "${_pc}" | grep -F -q -e "${_exclude_pat##*|}" 2>/dev/null
        then
          _has_excluded=1
        else
          _has_excluded=0
        fi
      fi
      if ! ((_has_excluded))
      then
        _post_hits="${_post_hits}${_hit_line}"$'\n'
      fi
    done <<< "${_raw_hits}"
    _raw_hits="${_post_hits%$'\n'}"
  fi

  # 6. 渲染
  if [[ -z "${_raw_hits}" ]]
  then
    _warn "没找到"
    return 0
  fi
  if ((_list_only))
  then
    printf "%s" "${_raw_hits}" | awk -F: '{print $1}' | sort -u
    return 0
  fi

  local _cur_file="" _cur_id="" _cur_title=""
  local _count=0
  while IFS=$'\t' read -r _f _rest
  do
    if ((_count >= _limit))
    then
      break
    fi
    # _rest 是 "line||content" 格式, 按 "||" 拆
    if [[ -n "${_f}" && -n "${_rest}" ]]
    then
      local _ln="${_rest%%||*}"
      local _content="${_rest#*||}"
      if [[ "${_f}" != "${_cur_file}" ]]
      then
        local _parsed
        _parsed="$(_parse_filename "$(basename "${_f}")")"
        _cur_id="${_parsed%%$'\t'*}"
        local _rest="${_parsed#*$'\t'}"
        _cur_title="${_rest%%$'\t'*}"
        printf "\n%s %s %s\n" \
          "$(_color_primary "${_cur_id:-?}")" \
          "$(_indicator "$(_detect_type "$(basename "${_f}")")")" \
          "$(_color_dim "${_cur_title:-$(basename "${_f}")}")"
        _cur_file="${_f}"
      fi
      # 高亮(简化:粗体显示命中行)
      printf "  %s %s\n" \
        "$(_color_dim "${_ln}:")" \
        "$(_highlight_match "${_content}" "${_final_pat}")"
      _count=$((_count + 1))
    fi
  done <<< "${_raw_hits}"
  printf "\n%s\n" "$(_color_dim "共 $((_count)) 条")"
}

_regex_escape() {
  # 转义 ERE metacharacters, 使字面量在 grep/rg/ag 中安全使用
  # 字符类说明: ] 需放在第一位(才字面), \\ 放最后(防止破坏字符类)
  printf '%s' "${1:-}" | sed 's/[][(){}.*+?|^$\\]/\\&/g'
}

# _build_or_args()
# 把 OR 多个 pattern 拆为标准化的 -e args, 写入全局数组 _OR_ARGS
# 用法: _build_or_args <first_pattern> <flag> [<flag_arg>...]
# 例: _build_or_args "${_final_pat}" -e  -> _OR_ARGS=("-e" "wifi" "-e" "url")
_build_or_args() {
  local _first="${1}"
  shift
  local _flag="${1:-}"
  _OR_ARGS=("${_flag}" "${_first}")
  shift
  local _sep_arg="${1:-}"
  # 如果模式包含 |, 拆开
  if [[ "${_first}" == *"|"* ]]
  then
    local _pp
    IFS='|' read -r -a _pp <<< "${_first}"
    _OR_ARGS=("${_flag}" "${_pp[0]}")
    local _i
    for _i in "${_pp[@]:1}"
    do
      _OR_ARGS+=("${_flag}" "${_i}")
    done
  fi
}

_join_regex() {
  local _sep="${1}"
  shift
  local _out=""
  local _first=1
  local _x
  for _x in "${@}"
  do
    if ((_first))
    then
      _out="${_x}"
      _first=0
    else
      _out="${_out}${_sep}${_x}"
    fi
  done
  printf "%s" "${_out}"
}

_highlight_match() {
  local _text="${1}"
  local _pat="${2}"
  # 简化:把第一个匹配项用 ANSI 标记包围
  # 去掉 pat 里的元字符再 highlight(只是视觉)
  local _kw="${_pat}"
  _kw="${_kw//\\/}"
  _kw="${_kw//./}"
  _kw="${_kw//\*/}"
  _kw="${_kw//|/:}"
  _kw="${_kw//\$/}"
  if [[ -z "${_kw}" ]]
  then
    printf "%s" "${_text}"
    return
  fi
  if color_enabled
  then
    printf "%s" "${_text}" | sed "s/${_kw}/$(_tput setaf 3)$(printf '%s' "${_kw}" | sed 's/[]\/$*.^|[]/\\&/g')$(_tput sgr0)/Ig" 2>/dev/null || printf "%s" "${_text}"
  else
    printf "%s" "${_text}"
  fi
}

_help_search() {
  cat <<EOF
${_ME} search - 搜索笔记

用法:
  ${_ME} search <keyword> [<keyword> ...]     # 隐式 AND
  ${_ME} search --and A --and B --or C --not D

选项:
      --and KEYWORD    AND 关键词
      --or  KEYWORD    OR 关键词
      --not KEYWORD    排除关键词
      --tag TAG        tag 搜索(#tag)
  -t, --type EXT      限定文件类型
  -l, --list          只列文件
  -n, --limit N       限制条数(默认 50)
      --no-color      关闭高亮

工具优先级: rg > ag > ack > grep(可用 MEMO_SEARCH_TOOL 强制)
EOF
}

# ============================================================================
# 命令: edit
# ============================================================================

edit() {
  local _selector="" _no_git=0 _editor_override=""
  while ((${#}))
  do
    case "${1:-}" in
      --no-git) _no_git=1; shift;;
      -e|--editor)
        _editor_override="${2:-}"
        shift 2 || _exit_1 "--editor 需要值"
        ;;
      -h|--help) _help_edit; return 0 ;;
      --) shift; break ;;
      -*) _exit_1 "edit 未知选项: ${1}" ;;
      *) _selector="${1}"; shift ;;
    esac
  done
  [[ -z "${_selector}" ]] && _exit_1 "用法: memo edit <id>"

  # 临时覆盖编辑器
  if [[ -n "${_editor_override}" ]]
  then
    EDITOR="${_editor_override}"
  fi

  local _fpath
  _fpath="$(_resolve_selector "${_selector}")" || _exit_1 "找不到笔记: ${_selector}"

  local _folder
  _folder="$(dirname "${_fpath}")"
  _ensure_index "${_folder}"

  "${EDITOR}" "${_fpath}"

  if ! ((_no_git))
  then
    _git_checkpoint "${_folder}" "edit: $(basename "${_fpath}")" || true
  fi
  _info "已更新: $(basename "${_fpath}")"
}

_help_edit() {
  cat <<EOF
${_ME} edit - 用 \$EDITOR 编辑笔记

用法:
  ${_ME} edit <id|title> [--no-git]
EOF
}

# ============================================================================
# 命令: delete
# ============================================================================

delete() {
  local _selector="" _archive=0 _force=0 _no_git=0
  while ((${#}))
  do
    case "${1:-}" in
      -a|--archive) _archive=1; shift ;;
      -f|--force)   _force=1; shift ;;
      --no-git)     _no_git=1; shift ;;
      -h|--help)    _help_delete; return 0 ;;
      --) shift; break ;;
      -*) _exit_1 "delete 未知选项: ${1}" ;;
      *) _selector="${1}"; shift ;;
    esac
  done
  [[ -z "${_selector}" ]] && _exit_1 "用法: memo delete <id>"

  local _fpath
  _fpath="$(_resolve_selector "${_selector}")" || _exit_1 "找不到笔记: ${_selector}"

  if [[ "${_force}" != "1" ]]
  then
    if ! _prompt_yes "确定删除 $(basename "${_fpath}")?"
    then
      _exit_1 "已取消"
    fi
  fi

  local _target="${_fpath}"
  local _folder
  _folder="$(dirname "${_fpath}")"
  if ((_archive))
  then
    local _archive_dir
    _archive_dir="$(_notebook_path)/archive"
    mkdir -p "${_archive_dir}"
    _ensure_index "${_archive_dir}"
    _target="${_archive_dir}/$(basename "${_fpath}")"
    if [[ -e "${_target}" ]]
    then
      _exit_1 "archive 中已存在同名文件: ${_target}"
    fi
  fi

  rm -f "${_fpath}"
  # 从 .index 移除
  local _parsed
  _parsed="$(_parse_filename "$(basename "${_fpath}")")"
  local _id="${_parsed%%$'\t'*}"
  _index_remove "${_folder}/.index" "${_id}"

  if ! ((_no_git))
  then
    if ((_archive))
    then
      _git_checkpoint "$(dirname "${_target}")" "archive: $(basename "${_fpath}")" || true
      _git_checkpoint "${_folder}" "archive: $(basename "${_fpath}")" || true
    else
      _git_checkpoint "${_folder}" "delete: $(basename "${_fpath}")" || true
    fi
  fi
  _info "已删除: $(basename "${_fpath}")"
}

_help_delete() {
  cat <<EOF
${_ME} delete - 删除笔记

用法:
  ${_ME} delete <id|title> [--archive] [--force] [--no-git]

选项:
  -a, --archive  移到 archive/ 文件夹
  -f, --force    不询问
      --no-git   不自动 commit
EOF
}

# ============================================================================
# 命令: sync
# ============================================================================

sync() {
  _git_sync "$(_notebook_path)"
}

# ============================================================================
# 命令: folders
# ============================================================================

folders() {
  local _sub="${1:-list}"
  shift || true
  case "${_sub}" in
    add)    folders_add "${@}" ;;
    mv)     folders_mv "${@}" ;;
    move)   folders_mv "${@}" ;;
    rm)     folders_rm "${@}" ;;
    ls)     folders_ls "${@}" ;;
    list)   folders_list "${@}" ;;
    show)   folders_show "${@}" ;;
    count)  folders_count "${@}" ;;
    -h|--help|"") _help_folders ;;
    *) _exit_1 "folders 未知子命令: ${_sub}" ;;
  esac
}

folders_add() {
  local _name="" _force=0
  while ((${#}))
  do
    case "${1:-}" in
      -f|--force) _force=1; shift;;
      -h|--help) _help_folders_add; return 0 ;;
      --) shift; break ;;
      -*) _exit_1 "folders add 未知选项: ${1}" ;;
      *) _name="${1}"; shift ;;
    esac
  done
  [[ -z "${_name}" ]] && _exit_1 "用法: memo folders add <name>"

  local _abs
  _abs="$(_resolve_folder_path "${_name}")"
  if [[ -d "${_abs}" ]]
  then
    if ((_force))
    then
      _warn "已存在: ${_name}"
      return 0
    fi
    _exit_1 "已存在: ${_name}"
  fi
  mkdir -p "${_abs}" || _exit_1 "创建失败"
  _ensure_index "${_abs}"
  # 自动 git
  local _parent
  _parent="$(dirname "${_abs}")"
  _git_checkpoint "${_parent}" "folders add: ${_name}" || true
  _info "创建: ${_name}"
}

folders_mv() {
  local _src="" _dst="" _force=0
  while ((${#}))
  do
    case "${1:-}" in
      -f|--force) _force=1; shift;;
      -h|--help) _help_folders_mv; return 0 ;;
      --) shift; break ;;
      -*) _exit_1 "folders mv 未知选项: ${1}" ;;
      *)
        if [[ -z "${_src}" ]]
        then
          _src="${1}"
        else
          _dst="${1}"
        fi
        shift
        ;;
    esac
  done
  [[ -z "${_src}" || -z "${_dst}" ]] && _exit_1 "用法: memo folders mv <src> <dst>"

  local _src_abs _dst_abs
  _src_abs="$(_resolve_folder_path "${_src}")"
  _dst_abs="$(_resolve_folder_path "${_dst}")"

  if [[ ! -d "${_src_abs}" ]]
  then
    _exit_1 "源不存在: ${_src}"
  fi
  if [[ -e "${_dst_abs}" ]]
  then
    if ! ((_force))
    then
      _exit_1 "目标已存在: ${_dst}"
    fi
  fi
  mkdir -p "$(dirname "${_dst_abs}")" || _exit_1 "创建父目录失败"
  mv "${_src_abs}" "${_dst_abs}" || _exit_1 "mv 失败"
  _ensure_index "${_dst_abs}"

  # 改所有子文件里的 ID 前缀(nb 不做这个,我们也不做)
  # 改 .index 里的 ID 太复杂,先不做

  local _nb
  _nb="$(_notebook_path)"
  _git_checkpoint "${_nb}" "folders mv: ${_src} -> ${_dst}" || true
  _info "已移动: ${_src} → ${_dst}"
}

folders_rm() {
  local _name="" _force=0
  while ((${#}))
  do
    case "${1:-}" in
      -f|--force) _force=1; shift;;
      -h|--help) _help_folders_add; return 0 ;;
      --) shift; break ;;
      -*) _exit_1 "folders rm 未知选项: ${1}" ;;
      *) _name="${1}"; shift ;;
    esac
  done
  [[ -z "${_name}" ]] && _exit_1 "用法: memo folders rm <name>"

  local _abs
  _abs="$(_resolve_folder_path "${_name}")"
  if [[ ! -d "${_abs}" ]]
  then
    _exit_1 "不存在: ${_name}"
  fi
  if ! ((_force))
  then
    if ! _prompt_yes "删除文件夹 ${_name} 及其内容?"
    then
      _exit_1 "已取消"
    fi
  fi
  rm -rf "${_abs}" || _exit_1 "rm 失败"
  local _nb
  _nb="$(_notebook_path)"
  _git_checkpoint "${_nb}" "folders rm: ${_name}" || true
  _info "已删除文件夹: ${_name}"
}

folders_ls() {
  local _folder=""
  while ((${#}))
  do
    case "${1:-}" in
      -h|--help) _help_folders_add; return 0 ;;
      --) shift; break ;;
      -*) _exit_1 "folders ls 未知选项: ${1}" ;;
      *) _folder="${1}"; shift ;;
    esac
  done
  local _target
  _target="$(_resolve_folder_path "${_folder}")"
  [[ ! -d "${_target}" ]] && _exit_1 "不存在: ${_folder:-.}"

  # 列出所有子目录 + .index
  printf "%s\n" "$(_color_primary "📁 ${_folder:-.}")"
  local _d
  while IFS= read -r _d
  do
    local _n
    _n="$(basename "${_d}")"
    local _count
    _count=$(find "${_d}" -maxdepth 1 -type f -not -name '.*' | wc -l)
    printf "  %s  %s  %s\n" \
      "$(_indicator "folder")" \
      "${_n}" \
      "$(_color_dim "${_count} notes")"
  done < <(_list_subdirs "${_target}")
}

folders_list() {
  local _recursive=0
  while ((${#}))
  do
    case "${1:-}" in
      -r|--recursive) _recursive=1; shift;;
      -h|--help) _help_folders_add; return 0 ;;
      --) shift; break ;;
      -*) _exit_1 "folders list 未知选项: ${1}" ;;
      *) shift ;;
    esac
  done
  local _nb
  _nb="$(_notebook_path)"
  if ((_recursive))
  then
    find "${_nb}" -mindepth 1 -type d 2>/dev/null | sort | while IFS= read -r _d
    do
      local _rel="${_d#${_nb}/}"
      [[ "${_rel}" == "" ]] && continue
      local _c
      _c=$(find "${_d}" -maxdepth 1 -type f -not -name '.*' | wc -l)
      printf "%s  %s\n" "$(_color_dim "${_rel}")" "$(_color_dim "(${_c})")"
    done
  else
    _list_subdirs "${_nb}" | while IFS= read -r _d
    do
      local _rel="${_d#${_nb}/}"
      local _c
      _c=$(find "${_d}" -maxdepth 1 -type f -not -name '.*' | wc -l)
      printf "%s  %s\n" "$(_color_dim "${_rel}")" "$(_color_dim "(${_c})")"
    done
  fi
}

folders_show() {
  local _name=""
  while ((${#}))
  do
    case "${1:-}" in
      -h|--help) _help_folders_add; return 0 ;;
      --) shift; break ;;
      -*) _exit_1 "folders show 未知选项: ${1}" ;;
      *) _name="${1}"; shift ;;
    esac
  done
  local _abs
  _abs="$(_resolve_folder_path "${_name}")"
  [[ ! -d "${_abs}" ]] && _exit_1 "不存在: ${_name:-.}"

  local _files
  _files="$(_list_files "${_abs}" 0)"
  local _c
  _c=$(printf "%s\n" "${_files}" | grep -c . || echo 0)
  printf "%s\n" "$(_color_primary "📁 ${_name}  (${_c} notes)")"
  local _f
  while IFS= read -r _f
  do
    local _parsed
    _parsed="$(_parse_filename "$(basename "${_f}")")"
    local _id="${_parsed%%$'\t'*}"
    local _rest="${_parsed#*$'\t'}"
    local _title="${_rest%%$'\t'*}"
    printf "  %s %s  %s\n" \
      "$(_color_primary "${_id:-?}")" \
      "$(_indicator "$(_detect_type "$(basename "${_f}")")")" \
      "${_title:-$(basename "${_f}")}"
  done <<< "${_files}"
}

folders_count() {
  local _name=""
  while ((${#}))
  do
    case "${1:-}" in
      -h|--help) _help_folders_add; return 0 ;;
      --) shift; break ;;
      -*) _exit_1 "folders count 未知选项: ${1}" ;;
      *) _name="${1}"; shift ;;
    esac
  done
  local _abs
  _abs="$(_resolve_folder_path "${_name}")"
  [[ ! -d "${_abs}" ]] && _exit_1 "不存在: ${_name:-.}"
  find "${_abs}" -maxdepth 1 -type f -not -name '.*' | wc -l
}

_help_folders() {
  cat <<EOF
${_ME} folders - 文件夹管理

子命令:
  ${_ME} folders add <name>      创建文件夹
  ${_ME} folders mv <src> <dst>  移动/重命名
  ${_ME} folders rm <name>       删除文件夹
  ${_ME} folders ls [path]       列出当前文件夹下的子目录
  ${_ME} folders list [-r]       列出所有子目录(可递归)
  ${_ME} folders show <path>     显示文件夹内的笔记
  ${_ME} folders count <path>    统计笔记数
EOF
}

_help_folders_add() {
  cat <<EOF
${_ME} folders add <name> [-f]
${_ME} folders mv <src> <dst> [-f]
${_ME} folders rm <name> [-f]
EOF
}

_help_folders_mv() {
  cat <<EOF
${_ME} folders mv <src> <dst> [-f]
EOF
}

# ============================================================================
# 命令: todo
# ============================================================================

todo() {
  local _sub="${1:-add}"
  shift || true
  case "${_sub}" in
    add)    todo_add "${@}" ;;
    ls|list) todo_list "${@}" ;;
    count)  todo_count "${@}" ;;
    -h|--help|"") _help_todo ;;
    *) _exit_1 "todo 未知子命令: ${_sub}" ;;
  esac
}

todo_add() {
  local _title="" _folder="" _tasks=() _no_git=0
  while ((${#}))
  do
    case "${1:-}" in
      -f|--folder)
        _folder="${2:-}"
        shift 2
        ;;
      -t|--task)
        _tasks+=("${2:-}")
        shift 2
        ;;
      --no-git) _no_git=1; shift;;
      -h|--help) _help_todo_add; return 0 ;;
      --) shift; break ;;
      -*) _exit_1 "todo add 未知选项: ${1}" ;;
      *) _title="${1}"; shift ;;
    esac
  done
  [[ -z "${_title}" ]] && _exit_1 "用法: memo todo add \"事项\" [-t 子项]"

  local _target
  _target="$(_resolve_folder_path "${_folder}")"
  if [[ ! -d "${_target}" ]]
  then
    if _prompt_yes "文件夹不存在,创建吗?"
    then
      _folder_create "${_folder}"
    else
      _exit_1 "已取消"
    fi
  fi
  _ensure_index "${_target}"

  local _idx="${_target}/.index"
  local _id
  if [[ -n "${_folder}" ]]
  then
    local _n
    _n=$(_next_id_in_folder "${_idx}" "${_folder}.")
    _id="${_folder}.${_n}"
  else
    _id="$(_next_id "${_idx}")"
  fi

  # 构造 todo 内容
  local _body=""
  _body="- [ ] ${_title}"
  local _t
  for _t in "${_tasks[@]}"
  do
    _body="${_body}
  - [ ] ${_t}"
  done
  local _final="# ${_title}

${_body}
"

  local _fname
  _fname="$(_build_filename "${_id}" "${_title}" "md")"
  local _fpath="${_target}/${_fname}"
  [[ -e "${_fpath}" ]] && _exit_1 "文件已存在: ${_fname}"
  printf "%s" "${_final}" > "${_fpath}" || _exit_1 "写文件失败"

  _index_add "${_idx}" "${_id}" "${_title}"
  if ! ((_no_git))
  then
    _git_checkpoint "${_target}" "todo: ${_title}" || true
  fi
  _info "创建 todo [${_id}]: ${_title}"
}

todo_list() {
  local _folder=""
  while ((${#}))
  do
    case "${1:-}" in
      -f|--folder)
        _folder="${2:-}"
        shift 2
        ;;
      -h|--help) _help_todo_add; return 0 ;;
      --) shift; break ;;
      -*) _exit_1 "todo list 未知选项: ${1}" ;;
      *) shift ;;
    esac
  done

  local _target
  _target="$(_resolve_folder_path "${_folder}")"
  [[ ! -d "${_target}" ]] && _exit_1 "不存在: ${_folder:-.}"

  local _files
  _files="$(_list_files "${_target}" 0)"

  printf "%s\n" "$(_color_primary "📋 Todos$([ -n "${_folder}" ] && printf " in ${_folder}")")"
  local _open=0 _done=0 _id _tstate _title _ind _f
  while IFS= read -r _f
  do
    _tstate="$(_is_todo_state "${_f}")"
    if [[ "${_tstate}" == "none" ]]
    then
      continue
    fi
    local _parsed
    _parsed="$(_parse_filename "$(basename "${_f}")")"
    _id="${_parsed%%$'\t'*}"
    local _rest="${_parsed#*$'\t'}"
    _title="${_rest%%$'\t'*}"
    if [[ "${_tstate}" == "done" ]]
    then
      _ind="✅"
      _done=$((_done + 1))
    else
      _ind="☐ "
      _open=$((_open + 1))
    fi
    printf "  %s %s  %s\n" \
      "$(_color_primary "${_id:-?}")" \
      "${_ind}" \
      "${_title:-$(basename "${_f}")}"
  done <<< "${_files}"
  printf "\n%s  %s  %s\n" \
    "$(_color_dim "open:")" "${_open}" \
    "$(_color_dim "done:")" "${_done}"
}

todo_count() {
  local _open=0 _done=0 _f
  local _files
  _files="$(_list_files "$(_notebook_path)" 1)"
  while IFS= read -r _f
  do
    local _s
    _s="$(_is_todo_state "${_f}")"
    case "${_s}" in
      done)   _done=$((_done + 1)) ;;
      open|mixed) _open=$((_open + 1)) ;;
    esac
  done <<< "${_files}"
  printf "open: %d  done: %d\n" "${_open}" "${_done}"
}

_help_todo() {
  cat <<EOF
${_ME} todo - Todo 管理

子命令:
  ${_ME} todo add "<事项>" [-t 子项] [-f folder]  创建 todo
  ${_ME} todo ls [folder]                         列出 todo
  ${_ME} todo count                               统计
  ${_ME} do <id>                                  标记完成(切换第一个 checkbox)
  ${_ME} undone <id>                              标记未完成

示例:
  ${_ME} todo add "买面包" -t "全麦" -t "吐司"
  ${_ME} do 1
  ${_ME} undone 1
EOF
}

_help_todo_add() {
  cat <<EOF
${_ME} todo add "<title>" [-t <task>]... [-f <folder>]
EOF
}

# ============================================================================
# 命令: do / done / undone
# ============================================================================

do_cmd() {
  local _selector="" _no_git=0
  while ((${#}))
  do
    case "${1:-}" in
      --no-git) _no_git=1; shift;;
      -h|--help)
        cat <<EOF
${_ME} do <id>       标记 todo 完成(切换第一个未完成项为已完成)
${_ME} done <id>     同 do
${_ME} undone <id>   取消完成(切换第一个已完成项为未完成)
EOF
        return 0
        ;;
      --) shift; break ;;
      -*) _exit_1 "do 未知选项: ${1}" ;;
      *) _selector="${1}"; shift ;;
    esac
  done
  [[ -z "${_selector}" ]] && _exit_1 "用法: memo do <id>"

  local _fpath
  _fpath="$(_resolve_selector "${_selector}")" || _exit_1 "找不到笔记: ${_selector}"

  local _tstate
  _tstate="$(_is_todo_state "${_fpath}")"
  if [[ "${_tstate}" == "none" ]]
  then
    _exit_1 "不是 todo 文件"
  fi

  # 用 awk 切换第一个未完成 → 完成(只改第一处)
  if _command_exists awk
  then
    local _tmp
    _tmp="$(mktemp)"
    awk '
      BEGIN { done = 0 }
      /^[[:space:]]*-[[:space:]]\[[[:space:]]\]/ && !done {
        # 保留前导空白, 后面直接拼 "- [x] "
        match($0, /^[[:space:]]*/)
        lead = substr($0, 1, RLENGTH)
        $0 = lead "- [x] " substr($0, RLENGTH + 6)
        done = 1
      }
      { print }
    ' "${_fpath}" > "${_tmp}" && mv "${_tmp}" "${_fpath}"
  fi

  if ! ((_no_git))
  then
    _git_checkpoint "$(dirname "${_fpath}")" "do: $(basename "${_fpath}")" || true
  fi
  _info "已标记完成: $(basename "${_fpath}")"
}

undone_cmd() {
  local _selector="" _no_git=0
  while ((${#}))
  do
    case "${1:-}" in
      --no-git) _no_git=1; shift;;
      -h|--help)
        cat <<EOF
${_ME} undone <id>   取消 todo 完成
EOF
        return 0
        ;;
      --) shift; break ;;
      -*) _exit_1 "undone 未知选项: ${1}" ;;
      *) _selector="${1}"; shift ;;
    esac
  done
  [[ -z "${_selector}" ]] && _exit_1 "用法: memo undone <id>"

  local _fpath
  _fpath="$(_resolve_selector "${_selector}")" || _exit_1 "找不到笔记: ${_selector}"
  if _command_exists awk
  then
    local _tmp
    _tmp="$(mktemp)"
    awk '
      BEGIN { done = 0 }
      /^[[:space:]]*-[[:space:]]\[[xX]\]/ && !done {
        match($0, /^[[:space:]]*/)
        lead = substr($0, 1, RLENGTH)
        $0 = lead "- [ ] " substr($0, RLENGTH + 6)
        done = 1
      }
      { print }
    ' "${_fpath}" > "${_tmp}" && mv "${_tmp}" "${_fpath}"
  fi

  if ! ((_no_git))
  then
    _git_checkpoint "$(dirname "${_fpath}")" "undone: $(basename "${_fpath}")" || true
  fi
  _info "已取消完成: $(basename "${_fpath}")"
}

# ============================================================================
# 杂项
# ============================================================================

version() {
  printf "%s %s\n" "$(_color_primary "${_ME}")" "${_VERSION}"
}

help() {
  cat <<EOF
$(_color_primary "${_ME}") v${_VERSION} - your notes, in your filesystem

$(printf "%s" "${_ME}") <command> [args]

核心命令:
  init                                初始化
  add "<title>" [-c TEXT] [-e] [-f PATH] 创建笔记
  ls [-a] [-n N] [-f PATH] [-t EXT]    列出
  show <id|title>                     查看
  search <keyword>... [--and|--or|--not|--tag]  搜索
  edit <id>                           编辑
  delete <id> [--archive] [--force]   删除/归档
  sync                                Git 同步

扩展命令:
  folders add|mv|rm|ls|list|show|count 文件夹管理
  todo add "<事项>" [-t 子项] [-f PATH]  todo 管理
  todo ls|list|count
  do|done <id>                       标记 todo 完成
  undone <id>                         取消完成

其他:
  version                             版本
  help                                本帮助

环境变量:
  NB_DIR                 笔记根目录(默认 ~/.nb)
  NB_DEFAULT_EXTENSION   默认扩展名(默认 md)
  EDITOR                 编辑器(默认从 PATH 自动选)
  MEMO_SEARCH_TOOL       强制搜索工具(rg/ag/ack/grep)
  NO_COLOR               禁用颜色输出
EOF
}

_prompt_yes() {
  local _q="${1:-确定?}"
  printf "%s [y/N] " "${_q}"
  local _ans
  read -r _ans
  case "$(_lower "${_ans}")" in
    y|yes) return 0 ;;
    *) return 1 ;;
  esac
}

# ============================================================================
# 主调度
# ============================================================================

main() {
  if ((${#} == 0))
  then
    help
    return 0
  fi
  # --debug: 开启调试追踪 (set -x), 可加在任何命令前
  if [[ "${1:-}" == "--debug" ]]
  then
    shift
    set -x
  fi
  local _cmd="${1}"
  shift
  # 命令分发
  case "${_cmd}" in
    init)              init "${@}" ;;
    add)               add "${@}" ;;
    ls|list)           list "${@}" ;;
    show|view)         show "${@}" ;;
    search|grep|q)     search "${@}" ;;
    edit|e)            edit "${@}" ;;
    delete|rm|d)       delete "${@}" ;;
    sync)              sync "${@}" ;;
    folders)           folders "${@}" ;;
    todo|todos)        todo "${@}" ;;
    do|done)           do_cmd "${@}" ;;
    undone)            undone_cmd "${@}" ;;
    version|--version|-V) version ;;
    help|--help|-h)    help ;;
    *)
      # 兼容短别名
      printf "%s 未知命令: %s\n" "$(_color_warn "!")" "${_cmd}" >&2
      printf "试试: %s help\n" "${_ME}" >&2
      return 1
      ;;
  esac
}

main "${@}"

