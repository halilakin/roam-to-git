import glob
import os
import re
from collections import defaultdict
from itertools import takewhile
from pathlib import Path
from typing import Dict, List, Match, Tuple
from roam_to_git.fs import note_filename


def read_markdown_directory(raw_directory: Path) -> Dict[str, str]:
    contents = {}
    for file in raw_directory.iterdir():
        if file.is_dir():
            # We recursively add the content of sub-directories.
            # They exists when there is a / in the note name.
            for child_name, content in read_markdown_directory(file).items():
                contents[f"{file.name}/{child_name}"] = content
        if not file.is_file():
            continue
        content = file.read_text(encoding="utf-8")
        parts = file.parts[len(raw_directory.parts) :]
        file_name = os.path.join(*parts)
        contents[file_name] = content
    return contents


def get_back_links(
    contents: Dict[str, str]
) -> Dict[str, List[Tuple[str, Match]]]:
    # Extract backlinks from the markdown
    forward_links = {
        file_name: extract_links(content)
        for file_name, content in contents.items()
    }
    back_links: Dict[str, List[Tuple[str, Match]]] = defaultdict(list)
    for file_name, links in forward_links.items():
        for link in links:
            back_links[f"{link.group(1)}.md"].append((file_name, link))
    return back_links


def get_block_refs(
    contents: Dict[str, str]
) -> Dict[str, List[Tuple[str, Match]]]:
    # Extract block refs from the markdown
    #     block_refs = {file_name: extract_block_refs(content) for file_name,
    #         content in contents.items()}
    #     back_links: Dict[str, List[Tuple[str, Match]]] = defaultdict(list)
    #     for file_name, links in forward_links.items():
    #         for link in links:
    #             back_links[f"{link.group(1)}.md"].append((file_name, link))
    #     return back_links
    pass


def fix_triple_backticks(content: str) -> str:
    return re.sub(r"- ```", r"\n```", content)


def format_markdown(contents: Dict[str, str], allowed_notes: List[str]) -> Dict[str, str]:
    back_links = get_back_links(contents)
    # Format and write the markdown files
    out = {}
    for file_name, content in contents.items():
        # We add the backlinks first, because they use the position of the caracters
        # of the regex matchs
        content = add_back_links(content, back_links[file_name])

        # Format content. Backlinks content will be formatted automatically.
        content = format_to_do(content)
        link_prefix = "../" * sum("/" in char for char in file_name)
        content = format_link(content, allowed_notes, link_prefix=link_prefix)
        if len(content) > 0:
            out[file_name] = content

    return out


def get_allowed_notes(dir: Path) -> List[str]:
    allowed_notes = []
    dirs_to_check = [dir] + [Path(f.path) for f in os.scandir(dir) if f.is_dir()]
    for dir in dirs_to_check:
        files = glob.glob(str(dir)+"/*")
        for file in files:
            if os.path.isfile(file):
                with open(file) as f:
                    for line in f:
                        match = re.match(r".*#public", line)
                        if match:
                            note_title = file.split('/')[-1][:-3]
                            allowed_notes.append(note_title)

    return allowed_notes


regex = r"(?i)\b((?:https?://|www\d{0,3}[.]|[a-z0-9.\-]+[.][a-z]{2,4}/)(?:[^\s()<>]+|\(([^\s()<>]+|(\([^\s()<>]+\)))*\))+(?:\(([^\s()<>]+|(\([^\s()<>]+\)))*\)|[^\s`!()\[\]{};:'\".,<>?«»“”‘’]))"


def process_hyperlinks(content):
    url = re.findall(regex, content)
    urls = [x[0] for x in url]
    print(f"Checking\n{content}")
    for url in urls:
        position = content.find(url)
        if position > 1 and content[position - 1] not in "(<":
            content = content.replace(url, f"<{url}>")
    return content


def format_markdown_notes(
    contents: Dict[str, str], notes_dir: Path, allowed_notes: List[str]
) -> Dict[str, str]:
    back_links = get_back_links(contents)
    # Format and write the markdown files
    out = {}
    for file_name, content in contents.items():
        for file_name in (file_name, os.path.basename(file_name)):
            if file_name[:-3] in allowed_notes:
                # We add the backlinks first, because they use the position of the caracters
                # of the regex matchs
                if "SKIP_BACKLINK_NOTES" not in os.environ:
                    content = add_back_links_notes(
                        content, notes_dir, file_name, back_links[file_name]
                    )

                # Format content. Backlinks content will be formatted automatically.
                content = format_to_do(content)
                content = process_hyperlinks(content)
                link_prefix = "../" * sum("/" in char for char in file_name)
                content = format_link(content, allowed_notes, link_prefix=link_prefix)
                content = convert_links(content)
                if len(content) > 0:
                    out[file_name] = content

    return out


def format_to_do(contents: str):
    contents = re.sub(r"{{\[\[TODO\]\]}} *", r"[ ] ", contents)
    contents = re.sub(r"{{\[\[DONE\]\]}} *", r"[x] ", contents)
    return contents


def extract_links(string: str) -> List[Match]:
    out = list(re.finditer(r"\[\[" r"([^\]\n]+)" r"\]\]", string)) + list(
        re.finditer(r"#" r"([^\], \n]+)" r"[, ]", string)
    )
    # Match attributes
    out.extend(
        re.finditer(
            r"(?:^|\n) *- "
            r"((?:[^:\n]|:[^:\n])+)"
            r"::",  # Match everything except ::
            string,
        )
    )
    return out


def add_back_links(content: str, back_links: List[Tuple[str, Match]]) -> str:
    if not back_links:
        return content
    files = sorted(
        set((file_name[:-3], match) for file_name, match in back_links),
        key=lambda e: (e[0], e[1].start()),
    )
    new_lines = []
    file_before = None
    for file, match in files:
        if file != file_before:
            new_lines.append(f"## [{file}](<{file}.md>)")
        file_before = file

        start_context_ = list(
            takewhile(lambda c: c != "\n", match.string[: match.start()][::-1])
        )
        start_context = "".join(start_context_[::-1])

        middle_context = match.string[match.start() : match.end()]

        end_context_ = takewhile(lambda c: c != "\n", match.string[match.end()])
        end_context = "".join(end_context_)

        context = (start_context + middle_context + end_context).strip()
        new_lines.extend([context, ""])
    backlinks_str = "\n".join(new_lines)
    return f"{content}\n# Backlinks\n{backlinks_str}\n"


def add_back_links_notes(
    content: str,
    notes_dir: Path,
    file_name: str,
    back_links: List[Tuple[str, Match]],
) -> str:
    if not back_links:
        return content
    files = sorted(
        set((file_name[:-3], match) for file_name, match in back_links),
        key=lambda e: (e[0], e[1].start()),
    )
    new_lines = []
    for file, match in files:

        start_context_ = list(
            takewhile(lambda c: c != "\n", match.string[: match.start()][::-1])
        )
        start_context = "".join(start_context_[::-1])

        middle_context = match.string[match.start() : match.end()]

        end_context_ = takewhile(lambda c: c != "\n", match.string[match.end()])
        end_context = "".join(end_context_)

        context = (start_context + middle_context + end_context).strip()
        extended_context = []
        with open(notes_dir / f"{file}.md") as input:
            appending = None
            for line in input:
                if line.startswith(context) and "-" in line:
                    extended_context.append(line)
                    appending = context[0 : context.index("-") + 1]
                    continue
                if appending:
                    if line.startswith(appending):
                        appending = None
                    else:
                        extended_context.append(line)
        new_lines.extend(["".join(extended_context), ""])
    backlinks_str = "\n".join(new_lines)
    content = fix_triple_backticks(content)
    return f"---\ntitle: {file_name[:-3]}\n---\n\n{content}\n{backlinks_str}\n"


def convert_links(line: str):
    keep_looking = True
    suffix = "{: .internal-link}"
    while keep_looking:
        match = re.search(r"\(<([^>]*)>\)", line)
        if match:
            converted_link = note_filename(match.group(1))[:-3]
            line = line.replace(match.group(0), f"(/{converted_link}){suffix}")
        else:
            keep_looking = False
    return line


def format_link(string: str, allowed_notes: List[str], link_prefix="") -> str:
    """Transform a RoamResearch-like link to a Markdown link.

    @param link_prefix: Add the given prefix before all links.
        WARNING: not robust to special characters.
    """
    # Regex are read-only and can't parse [[[[recursive]] [[links]]]], but they do the job.
    # We use a special syntax for links that can have SPACES in them
    # Format internal reference: [[mynote]]
    string = re.sub(
        r"\[\["  # We start with [[
        # TODO: manage a single ] in the tag
        r"([^\]\n]+)" r"\]\]",  # Everything except ]
        rf"[\1](<{link_prefix}\1.md>)",
        string,
        flags=re.MULTILINE,
    )

    # Format hashtags: #mytag
    string = re.sub(
        r"#([a-zA-Z-_0-9]+)",
        rf"[\1](<{link_prefix}\1.md>)",
        string,
        flags=re.MULTILINE,
    )

    # Format attributes
    string = re.sub(
        r"(^ *- )"  # Match the beginning, like '  - '
        r"(([^:\n]|:[^:\n])+)"  # Match everything except ::
        r"::",
        rf"\1**[\2](<{link_prefix}\2.md>):**",  # Format Markdown link
        string,
        flags=re.MULTILINE,
    )

    for link in re.findall(r'<[^>]*\.md>', string):
        if link[1:-4] not in allowed_notes:
            print(f"{link} not allowed")
            string = string.replace(link, "")
    return string
