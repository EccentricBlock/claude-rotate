# Changing a convention

A rule change isn't finished when the rule is written. Every file written under
the previous rule still contradicts it, and nothing flags that on its own.

- Sweep every file the new rule governs, in the same commit series that adds it.
- Record the search you ran in the commit body, so the next reader can repeat
  it and get the same set.
- Fix each hit, or keep it and name the carve-out that covers it. Never leave a
  hit unexplained.
- Recorded history, such as past commit messages, is never rewritten to match a
  new rule.
