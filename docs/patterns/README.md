# Pattern #3 — Optimistic Locking cho tính năng sửa điểm

## Hai bản

| Bản | Tệp | Mô tả |
|---|---|---|
| **Trước khi sửa** | `sua_diem_truoc_khi_sua.py` | Logic cũ trích nguyên trạng: không kiểm tra version, không kiểm tra miền điểm, xoá nhận xét khi thiếu field, và lỗi `attempt.quiz`. |
| **Sau khi sửa** | `../../web/grade_service.py` | Service dùng chung: kiểm tra `version`, kiểm tra miền điểm, giữ nhận xét khi không gửi, lấy `Quiz` theo `quiz_id`. |
| | `../../web/blueprints/quiz.py` | `assignment_grade` dùng service, trả 409 khi xung đột. |
| | `../../web/blueprints/admin.py` | `grade_quiz_adjust`, `grade_assignment_adjust` dùng service. |
| | `../../web/models.py` | Cột `version` trên `submissions` và `quiz_attempts`. |

## Bằng chứng

`evidence.txt` — kết quả chạy `tools/pattern_evidence.py`, in rõ before/after cho cả 3 lỗi.

Chạy lại:

```powershell
.venv\Scripts\python.exe tools\pattern_evidence.py
.venv\Scripts\python.exe -m pytest tests\test_grade_optimistic.py -q
```

## Ba lỗi đã xử lý

| Mã | Lỗi | Bản trước | Bản sau |
|---|---|---|---|
| V01 | Mất cập nhật khi hai người sửa cùng lúc | Lưu sau ghi đè, không báo | 409 Conflict, không ghi đè |
| V02 | 500 khi chỉnh điểm quiz | `attempt.quiz` → AttributeError | Lấy `Quiz` theo `quiz_id`, tính `passed` đúng |
| V03 | Điểm ngoài miền + mất nhận xét | Nhận 99/-1/NaN; feedback thành `""` | Từ chối ngoài `[0, max_score]`; giữ feedback khi không gửi |

## Báo cáo

`../Bao_cao_kiem_thu_sua_diem.docx` (và bản PDF) — theo cấu trúc báo cáo kiểm thử mẫu.
