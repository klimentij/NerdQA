#!/bin/bash

# Remove the directories from Git cache
git rm -r --cached "backend/output"
git rm -r --cached "output"

# Create a commit for the removal
git commit -m "Remove output directories from Git history"

# Push the changes
echo "Please review the changes and then push to your repository"
echo "You can push using: git push origin <your-branch-name>" 