from core import memos
from core.workflow import ADMIN, ASSIGNED, COMPLETED, IN_REVIEW, RE_REVIEW, RECEIVED, REVIEWER

ACTIVE_STATUSES = (ASSIGNED, IN_REVIEW, RE_REVIEW)


def sort_cases(cases):
    return sorted(cases, key=lambda c: c.get("registered_at") or "", reverse=True)


def group_cases(cases, user):
    if user["role"] == REVIEWER:
        mine = [c for c in cases if c.get("assignee") == user["uid"]]
        return {
            "내 대기 목록": sort_cases([c for c in mine if c.get("status") in ACTIVE_STATUSES]),
            "완료 목록": sort_cases([c for c in mine if c.get("status") == COMPLETED]),
        }
    if user["role"] == ADMIN:
        return {
            "배정 대기": sort_cases([c for c in cases if c.get("status") == RECEIVED]),
            "진행 중": sort_cases([c for c in cases if c.get("status") in ACTIVE_STATUSES]),
            "완료": sort_cases([c for c in cases if c.get("status") == COMPLETED]),
        }
    return {}


class FirestoreReviewStore:
    def __init__(self, db):
        self.db = db

    def _where(self, collection, field, value):
        from google.cloud.firestore_v1.base_query import FieldFilter
        query = self.db.collection(collection).where(filter=FieldFilter(field, "==", value))
        return [doc.to_dict() | {"id": doc.id} for doc in query.stream()]

    def get_case(self, case_id):
        snap = self.db.collection("cases").document(case_id).get()
        return snap.to_dict() if snap.exists else None

    def list_cases(self):
        return [doc.to_dict() for doc in self.db.collection("cases").stream()]

    def count_images(self, case_id):
        return len(self._where("images", "case_id", case_id))

    def get_user_role(self, uid):
        snap = self.db.collection("users").document(uid).get()
        return snap.to_dict().get("role") if snap.exists else None

    def list_users(self):
        users = [doc.to_dict() | {"id": doc.id} for doc in self.db.collection("users").stream()]
        return sorted(users, key=lambda u: u.get("name") or "")

    def list_status_logs(self, case_id):
        return sorted(self._where("status_logs", "case_id", case_id), key=lambda log: log["at"])

    def list_histories(self, case_id):
        return self._where("processing_history", "case_id", case_id)

    def apply_transition(self, case_id, expected_from, to_status, assignee_uid, log):
        from google.cloud import firestore

        case_ref = self.db.collection("cases").document(case_id)
        log_ref = self.db.collection("status_logs").document()

        @firestore.transactional
        def run(transaction):
            snap = case_ref.get(transaction=transaction)
            if not snap.exists or snap.to_dict().get("status") != expected_from:
                return False
            changes = {"status": to_status, "updated_at": log["at"]}
            if assignee_uid:
                changes["assignee"] = assignee_uid
            transaction.update(case_ref, changes)
            transaction.set(log_ref, log)
            return True

        return run(self.db.transaction())

    def get_memo(self, memo_id):
        snap = self.db.collection("memos").document(memo_id).get()
        return snap.to_dict() if snap.exists else None

    def list_memos(self, case_id):
        return self._where("memos", "case_id", case_id)

    def has_report(self, case_id):
        return memos.has_report(self.list_memos(case_id))

    def add_memo(self, memo_id, memo):
        from google.api_core.exceptions import AlreadyExists
        try:
            self.db.collection("memos").document(memo_id).create(memo)
            return True
        except AlreadyExists:
            return False

    def update_memo(self, memo_id, expected_content, changes):
        from google.cloud import firestore

        memo_ref = self.db.collection("memos").document(memo_id)

        @firestore.transactional
        def run(transaction):
            snap = memo_ref.get(transaction=transaction)
            if not snap.exists or snap.to_dict().get("content") != expected_content:
                return False
            transaction.update(memo_ref, changes)
            return True

        return run(self.db.transaction())
