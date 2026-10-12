#!/usr/bin/env bash
# Persist a directory to a branch of this repository (used for the site's latest data and the scoreboard).
# Usage: store.sh pull <branch> <dir>        copy the branch's files into <dir> (empty dir if the branch is missing)
#        store.sh push <branch> <dir> [--squash]   commit <dir> to the branch; --squash replaces its history (single commit)
set -euo pipefail
cmd=$1; branch=$2; dir=$3; flag=${4:-}
remote="https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"
mkdir -p "$dir"
case "$cmd" in
  pull)
    tmp=$(mktemp -d)
    if git ls-remote --exit-code --heads "$remote" "$branch" >/dev/null 2>&1; then
      git clone --quiet --depth 1 --branch "$branch" "$remote" "$tmp"
      rsync -a --exclude .git "$tmp"/ "$dir"/
      echo "pulled $branch: $(ls "$dir" | wc -l) files"
    else
      echo "branch $branch does not exist yet"
    fi ;;
  push)
    tmp=$(mktemp -d)
    git config --global user.name "github-actions[bot]"
    git config --global user.email "41898282+github-actions[bot]@users.noreply.github.com"
    if [ "$flag" = "--squash" ] || ! git ls-remote --exit-code --heads "$remote" "$branch" >/dev/null 2>&1; then
      git init --quiet "$tmp"; git -C "$tmp" checkout --quiet -b "$branch"; git -C "$tmp" remote add origin "$remote"
      rsync -a --exclude .git "$dir"/ "$tmp"/
      git -C "$tmp" add -A; git -C "$tmp" commit --quiet -m "update $branch $(date -u +%FT%TZ)"
      git -C "$tmp" push --quiet --force origin "$branch"
    else
      for attempt in 1 2 3; do
        rm -rf "$tmp"; tmp=$(mktemp -d)
        git clone --quiet --depth 1 --branch "$branch" "$remote" "$tmp"
        rsync -a --delete --exclude .git "$dir"/ "$tmp"/
        git -C "$tmp" add -A
        if git -C "$tmp" diff --cached --quiet; then echo "no changes"; exit 0; fi
        git -C "$tmp" commit --quiet -m "update $branch $(date -u +%FT%TZ)"
        git -C "$tmp" push --quiet origin "$branch" && break || sleep 3
      done
    fi
    echo "pushed $branch" ;;
esac
