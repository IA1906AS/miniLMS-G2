# Danh sách endpoint — miniLMS

Tổng cộng **140** route (sinh tự động từ `url_map`, khớp Phụ lục A của file đặc tả).

## Trang công khai & dashboard (7)

| Method | Endpoint | Chức năng | Vai trò |
|---|---|---|---|
| `GET` | `/` | Trang chủ | Tất cả |
| `GET` | `/courses` | Tra cứu khoá học + bộ lọc | Tất cả |
| `GET, POST` | `/courses/<course_id>` | Chi tiết khoá / đăng ký | Tất cả (POST: SV) |
| `GET` | `/courses/<course_id>/preview/<int:lesson_id>` | Học thử bài free preview | Tất cả |
| `GET` | `/dashboard` | Dashboard theo vai trò | SV, GV, QT |
| `GET` | `/instructors` | Danh sách giảng viên | Tất cả |
| `GET` | `/members/<user_id>` | Hồ sơ thành viên | Đã đăng nhập |

## Xác thực (5)

| Method | Endpoint | Chức năng | Vai trò |
|---|---|---|---|
| `GET, POST` | `/forgot-password` | Yêu cầu khôi phục mật khẩu | Khách |
| `GET, POST` | `/login` | Đăng nhập | Khách |
| `POST` | `/logout` | Đăng xuất | Đã đăng nhập |
| `GET, POST` | `/register` | Đăng ký tài khoản | Khách |
| `GET, POST` | `/reset-password/<token>` | Đặt mật khẩu mới từ token | Khách |

## Sinh viên (28)

| Method | Endpoint | Chức năng | Vai trò |
|---|---|---|---|
| `GET` | `/certificates` | Danh sách chứng chỉ | SV |
| `GET` | `/certificates/<code>` | Chi tiết chứng chỉ | SV |
| `POST` | `/enroll` | Ghi danh bằng mã | SV |
| `GET` | `/forum` | Diễn đàn các khoá | SV |
| `GET` | `/forum/<course_id>` | Diễn đàn một khoá | SV |
| `POST` | `/forum/<course_id>/post/<int:post_id>/delete` | Xoá bình luận của mình | SV |
| `POST` | `/forum/<course_id>/post/<int:post_id>/edit` | Sửa bình luận của mình | SV |
| `GET` | `/forum/<course_id>/topic/<int:topic_id>` | Chi tiết chủ đề | SV |
| `POST` | `/forum/<course_id>/topic/<int:topic_id>/delete` | Xoá chủ đề của mình | SV |
| `POST` | `/forum/<course_id>/topic/<int:topic_id>/edit` | Sửa chủ đề của mình | SV |
| `POST` | `/forum/<course_id>/topic/<int:topic_id>/reply` | Trả lời chủ đề | SV |
| `POST` | `/forum/<course_id>/topic/new` | Tạo chủ đề | SV |
| `GET` | `/grades` | Bảng điểm cá nhân | SV |
| `GET` | `/leaderboard` | Bảng xếp hạng | SV |
| `GET` | `/messages` | Hộp thư | SV |
| `GET` | `/messages/<instructor_id>` | Hội thoại với giảng viên | SV |
| `POST` | `/messages/<instructor_id>/send` | Gửi tin nhắn | SV |
| `GET` | `/my-courses` | Khoá đã ghi danh + tiến độ | SV |
| `GET` | `/my-courses/<course_id>/learn` | Giao diện học khoá | SV |
| `GET` | `/my-courses/<course_id>/learn/<int:lesson_id>` | Nội dung bài học + tài liệu | SV |
| `POST` | `/my-courses/<course_id>/learn/<int:lesson_id>/complete` | Đánh dấu hoàn thành bài | SV |
| `GET` | `/notifications` | Danh sách thông báo | SV |
| `POST` | `/notifications/<int:notification_id>/read` | Đánh dấu đã đọc | SV |
| `GET` | `/profile` | Hồ sơ cá nhân | SV |
| `GET, POST` | `/profile/edit` | Sửa hồ sơ | SV |
| `GET, POST` | `/profile/password` | Đổi mật khẩu | SV |
| `GET` | `/progress` | Tiến độ học tập | SV |
| `GET, POST` | `/settings` | Cài đặt nhận email | SV |

## Quiz & bài tập (8)

| Method | Endpoint | Chức năng | Vai trò |
|---|---|---|---|
| `GET` | `/assignments/<int:assignment_id>` | Chi tiết bài tập | SV, GV, QT |
| `POST` | `/assignments/<int:assignment_id>/submissions/<int:submission_id>/grade` | Chấm điểm bài nộp | GV, QT |
| `POST` | `/assignments/<int:assignment_id>/submit` | Nộp bài tập (văn bản + tệp) | SV |
| `GET` | `/quizzes/<int:quiz_id>` | Giới thiệu bài kiểm tra | SV |
| `GET` | `/quizzes/<int:quiz_id>/attempts/<int:attempt_id>` | Làm bài (đếm ngược) | SV |
| `GET` | `/quizzes/<int:quiz_id>/attempts/<int:attempt_id>/result` | Xem kết quả bài kiểm tra | SV, GV, QT |
| `POST` | `/quizzes/<int:quiz_id>/attempts/<int:attempt_id>/submit` | Nộp bài kiểm tra | SV |
| `POST` | `/quizzes/<int:quiz_id>/start` | Bắt đầu lượt làm bài | SV |

## Tệp & ảnh (6)

| Method | Endpoint | Chức năng | Vai trò |
|---|---|---|---|
| `POST` | `/attachments/<int:attachment_id>/delete` | Xoá tài liệu bài giảng | GV, QT |
| `GET` | `/attachments/<int:attachment_id>/download` | Tải tài liệu (kiểm quyền) | SV (ghi danh), GV, QT |
| `GET` | `/avatar/<user_id>` | Hiển thị ảnh đại diện | Đã đăng nhập |
| `POST` | `/lessons/<int:lesson_id>/attachments` | Tải tài liệu bài giảng | GV, QT |
| `POST` | `/profile/avatar` | Tải ảnh đại diện | SV, GV, QT |
| `GET` | `/submissions/<int:submission_id>/download` | Tải tệp bài nộp | SV (chủ bài), GV, QT |

## Giảng viên (36)

| Method | Endpoint | Chức năng | Vai trò |
|---|---|---|---|
| `GET` | `/instructor/assignments` | Bài tập của giảng viên | GV |
| `GET` | `/instructor/certificates` | Chứng chỉ của khoá | GV |
| `POST` | `/instructor/certificates/<int:certificate_id>/revoke` | Thu hồi chứng chỉ | GV |
| `POST` | `/instructor/chapters/<int:chapter_id>/lessons` | Thêm bài học | GV |
| `GET` | `/instructor/courses` | Khoá học phụ trách | GV |
| `POST` | `/instructor/courses/<course_id>/assignments` | Tạo bài tập | GV |
| `POST` | `/instructor/courses/<course_id>/certificates/issue` | Cấp chứng chỉ | GV |
| `POST` | `/instructor/courses/<course_id>/chapters` | Thêm chương | GV |
| `GET` | `/instructor/courses/<course_id>/curriculum` | Chương trình khoá | GV |
| `GET, POST` | `/instructor/courses/<course_id>/edit` | Sửa khoá học | GV |
| `POST` | `/instructor/courses/<course_id>/live` | Tạo live session | GV |
| `GET, POST` | `/instructor/courses/<course_id>/quizzes/new` | Tạo bài kiểm tra | GV |
| `GET` | `/instructor/courses/<course_id>/reports` | Báo cáo khoá học | GV |
| `GET` | `/instructor/courses/<course_id>/reports/export` | Xuất CSV báo cáo khoá | GV |
| `GET` | `/instructor/courses/<course_id>/students` | Danh sách SV trong khoá | GV |
| `POST` | `/instructor/courses/<course_id>/students/<student_id>/remove` | Xoá SV khỏi khoá | GV |
| `POST` | `/instructor/courses/<course_id>/students/add` | Thêm SV theo email | GV |
| `GET, POST` | `/instructor/courses/new` | Tạo khoá học | GV |
| `GET` | `/instructor/forum` | Diễn đàn khoá | GV |
| `POST` | `/instructor/forum/<int:topic_id>/moderate` | Kiểm duyệt chủ đề | GV |
| `GET` | `/instructor/grades` | Bảng điểm lớp | GV |
| `POST` | `/instructor/lessons/<int:lesson_id>/delete` | Xoá bài học | GV |
| `GET` | `/instructor/live` | Live session | GV |
| `POST` | `/instructor/live/<int:session_id>/delete` | Xoá live session | GV |
| `GET` | `/instructor/messages` | Hộp thư giảng viên | GV |
| `GET` | `/instructor/messages/<student_id>` | Hội thoại với sinh viên | GV |
| `POST` | `/instructor/messages/<student_id>/send` | Gửi tin nhắn | GV |
| `POST` | `/instructor/notifications` | Gửi thông báo lớp | GV |
| `GET` | `/instructor/notifications` | Thông báo lớp học | GV |
| `GET` | `/instructor/profile` | Hồ sơ giảng viên | GV |
| `GET, POST` | `/instructor/profile/edit` | Sửa hồ sơ giảng viên | GV |
| `GET, POST` | `/instructor/profile/password` | Đổi mật khẩu | GV |
| `POST` | `/instructor/questions/<int:question_id>/delete` | Xoá câu hỏi | GV |
| `GET` | `/instructor/quizzes` | Bài kiểm tra của giảng viên | GV |
| `GET, POST` | `/instructor/quizzes/<int:quiz_id>/questions` | Quản lý câu hỏi | GV |
| `GET` | `/instructor/reports/export` | Xuất báo cáo tổng hợp | GV |

## Quản trị (43)

| Method | Endpoint | Chức năng | Vai trò |
|---|---|---|---|
| `GET` | `/admin/assignments` | Bài tập toàn hệ thống | QT |
| `POST` | `/admin/assignments/<int:assignment_id>/delete` | Xoá bài tập | QT |
| `GET` | `/admin/audit` | Nhật ký hoạt động | QT |
| `GET` | `/admin/badges` | Quản lý huy hiệu | QT |
| `POST` | `/admin/badges/<int:badge_id>/delete` | Xoá huy hiệu | QT |
| `POST` | `/admin/badges/new` | Tạo huy hiệu | QT |
| `GET` | `/admin/categories` | Quản lý danh mục | QT |
| `POST` | `/admin/categories/<int:cat_id>/delete` | Xoá danh mục | QT |
| `POST` | `/admin/categories/new` | Tạo danh mục | QT |
| `GET` | `/admin/certificates` | Quản lý chứng chỉ | QT |
| `POST` | `/admin/certificates/<int:cert_id>/revoke` | Thu hồi chứng chỉ | QT |
| `POST` | `/admin/certificates/issue` | Cấp chứng chỉ | QT |
| `GET` | `/admin/courses` | Danh sách toàn bộ khoá học | QT |
| `GET` | `/admin/courses/<course_id>` | Chi tiết khoá học (admin) | QT |
| `POST` | `/admin/courses/<course_id>/delete` | Xoá khoá học | QT |
| `POST` | `/admin/courses/<course_id>/reassign` | Chuyển giảng viên phụ trách | QT |
| `POST` | `/admin/courses/<course_id>/status` | Đổi trạng thái khoá | QT |
| `GET` | `/admin/dashboard` | Dashboard quản trị | QT |
| `GET` | `/admin/forum` | Kiểm duyệt diễn đàn | QT |
| `POST` | `/admin/forum/<int:topic_id>/moderate` | Ghim/khoá/xoá chủ đề | QT |
| `GET` | `/admin/grades` | Bảng điểm toàn hệ thống | QT |
| `POST` | `/admin/grades/assignment/<int:submission_id>/adjust` | Chỉnh điểm bài tập | QT |
| `POST` | `/admin/grades/quiz/<int:attempt_id>/adjust` | Chỉnh điểm quiz | QT |
| `GET` | `/admin/live` | Quản lý live session | QT |
| `POST` | `/admin/live/<int:session_id>/delete` | Xoá live session | QT |
| `GET` | `/admin/notifications` | Gửi thông báo hệ thống | QT |
| `POST` | `/admin/notifications/send` | Gửi thông báo (form) | QT |
| `GET` | `/admin/quizzes` | Bài kiểm tra toàn hệ thống | QT |
| `POST` | `/admin/quizzes/<int:quiz_id>/delete` | Xoá bài kiểm tra | QT |
| `GET` | `/admin/reports` | Báo cáo tổng hợp | QT |
| `GET` | `/admin/reports/courses` | Báo cáo theo khoá học | QT |
| `GET` | `/admin/reports/users` | Báo cáo theo người dùng | QT |
| `GET` | `/admin/settings` | Cài đặt hệ thống | QT |
| `POST` | `/admin/settings` | Lưu cài đặt hệ thống | QT |
| `GET` | `/admin/settings/payments` | Cài đặt thanh toán | QT |
| `POST` | `/admin/settings/payments` | Lưu thanh toán | QT |
| `GET` | `/admin/settings/roles` | Cấu hình phân quyền | QT |
| `POST` | `/admin/settings/roles` | Lưu phân quyền | QT |
| `GET` | `/admin/users` | Danh sách & lọc người dùng | QT |
| `GET` | `/admin/users/<user_id>` | Chi tiết người dùng | QT |
| `POST` | `/admin/users/<user_id>/lock` | Khoá tài khoản | QT |
| `POST` | `/admin/users/<user_id>/role` | Đổi vai trò | QT |
| `POST` | `/admin/users/<user_id>/unlock` | Mở khoá tài khoản | QT |

## REST API (7)

| Method | Endpoint | Chức năng | Vai trò |
|---|---|---|---|
| `GET` | `/api/assignments/<int:assignment_id>` | Chi tiết bài tập | SV, GV, QT |
| `GET` | `/api/courses` | Danh sách khoá công khai | Tất cả |
| `GET` | `/api/courses/<course_id>` | Chi tiết khoá học | Tất cả |
| `GET` | `/api/courses/<course_id>/grades` | Điểm theo khoá học | SV, GV, QT |
| `GET` | `/api/docs` | Swagger UI | Tất cả |
| `GET` | `/api/me` | Thông tin người dùng hiện tại | Đã đăng nhập |
| `GET` | `/api/openapi.json` | Đặc tả OpenAPI | Tất cả |
