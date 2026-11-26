"""The check, in the background, of the versions of the working branch sent to the remote by others and not received
here yet: on opening the project and on moving to another branch, instead of asking every time to receive. Only the
branches of the remote are read (nothing is downloaded, the project does not change); the main window then asks to
receive, if there is something new."""
from PySide6.QtCore import QThread, Signal

from arcadia_tool.storage.repository import remote_branch_heads

_RUNNING = set()  # checks still going: kept alive until they end (also if the window that started them closed)


class UpdateCheck(QThread):
    """Reads the branches of the remote of `url`; done(self) or failed(self), with `heads` or `error`. path, branch,
    reason: the project and the branch it was started for, and why (said in the question)."""
    done = Signal(object)
    failed = Signal(object)

    def __init__(self, url, credentials, path, branch, reason):
        super().__init__()
        self.url, self.credentials = url, credentials
        self.path, self.branch, self.reason = path, branch, reason
        self.heads, self.error = None, ""
        _RUNNING.add(self)
        self.finished.connect(lambda: _RUNNING.discard(self))

    def run(self):
        try:
            self.heads = remote_branch_heads(self.url, **self.credentials)
            self.done.emit(self)
        except Exception as exc:
            self.error = str(exc) or exc.__class__.__name__
            self.failed.emit(self)


def news(project, heads):
    """How many versions of the working branch of the remote (heads: {branch: version}) the project lacks: None if
    none (or the branch is not on the remote); 0 if there are some, not downloaded yet (how many is not known)."""
    theirs = heads.get(project.push_branch())
    if not theirs:
        return None
    repository, head = project.repository, project.repository.head()
    try:
        repository.version(theirs)
    except KeyError:
        return 0  # a version never downloaded here: new
    if head is not None and repository.is_ancestor(theirs, head):
        return None
    return len(repository.versions_between(head, theirs))
