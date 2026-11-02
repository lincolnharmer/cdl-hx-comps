//
// Copyright (c) 2026, kW Engineering
// Licensed under the Academic Free License version 3.0
//

**
** A refusal to resolve. The message names what was refused: the
** parameter, expression, child, connector or unit group, and why. The
** resolver never guesses, so every case it cannot settle ends here.
**
const class CdlResolveErr : Err
{
  ** Construct with the message that names what was refused
  new make(Str msg, Err? cause := null) : super(msg, cause) {}
}
