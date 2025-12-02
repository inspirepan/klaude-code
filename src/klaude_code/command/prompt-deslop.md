---
description: Remove AI code slop
from: https://cursor.com/cn/link/command?name=deslop&text=%23%20Remove%20AI%20code%20slop%0A%0ACheck%20the%20diff%20against%20main%2C%20and%20remove%20all%20AI%20generated%20slop%20introduced%20in%20this%20branch.%0A%0AThis%20includes%3A%0A-%20Extra%20comments%20that%20a%20human%20wouldn%27t%20add%20or%20is%20inconsistent%20with%20the%20rest%20of%20the%20file%0A-%20Extra%20defensive%20checks%20or%20try%2Fcatch%20blocks%20that%20are%20abnormal%20for%20that%20area%20of%20the%20codebase%20(especially%20if%20called%20by%20trusted%20%2F%20validated%20codepaths)%0A-%20Casts%20to%20any%20to%20get%20around%20type%20issues%0A-%20Any%20other%20style%20that%20is%20inconsistent%20with%20the%20file%0A%0AReport%20at%20the%20end%20with%20only%20a%201-3%20sentence%20summary%20of%20what%20you%20changed
---

Check the diff against main, and remove all AI generated slop introduced in this branch.

This includes:
- Extra comments that a human wouldn't add or is inconsistent with the rest of the file
- Extra defensive checks or try/catch blocks that are abnormal for that area of the codebase (especially if called by trusted / validated codepaths)
- Casts to any to get around type issues
- Any other style that is inconsistent with the file

Report at the end with only a 1-3 sentence summary of what you changed