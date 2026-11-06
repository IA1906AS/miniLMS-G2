# LMS – Đặc tả chức năng theo vai trò (Web)

Hệ thống có 4 vai trò: **Admin**, **Giảng viên (GV)**, **Sinh viên (SV)**, **Khách (chưa đăng nhập)**.

---

## 1. KHÁCH (Guest – chưa đăng nhập)

### Trang truy cập được
| Route | Nội dung hiển thị | Hành động được phép |
|---|---|---|
| `/` (Trang chủ) | Banner giới thiệu, danh sách khóa học nổi bật, số liệu thống kê | Xem, bấm vào khóa học |
| `/courses` | Danh sách toàn bộ khóa học công khai, filter theo danh mục/tag | Xem, lọc, tìm kiếm |
| `/courses/:id` | Trang chi tiết khóa học: mô tả, chương trình, giảng viên, đánh giá, giá | Xem thông tin; bài học demo (nếu GV đánh dấu free preview) |
| `/instructors` | Danh sách giảng viên công khai | Xem hồ sơ GV |
| `/login` | Form đăng nhập | Đăng nhập bằng email/password hoặc OAuth |
| `/register` | Form đăng ký tài khoản | Tạo tài khoản mới (vai trò mặc định: SV) |
| `/forgot-password` | Form reset mật khẩu | Gửi email reset |

### Bị chặn / redirect
- Mọi route khác → redirect về `/login`
- Không thấy nội dung bài học đầy đủ
- Không thấy diễn đàn nội bộ, điểm số, chứng chỉ

---

## 2. SINH VIÊN (Student – đã đăng nhập)

### Layout
- Sidebar hoặc top nav: Dashboard, Khóa học của tôi, Khám phá, Thông báo, Hồ sơ

### Trang & chức năng
| Route | Nội dung hiển thị | Hành động được phép |
|---|---|---|
| `/dashboard` | Tiến độ học tổng quan, khóa học đang học, bài học tiếp theo, streak, thông báo mới | Bấm tiếp tục học |
| `/courses` | Tất cả khóa công khai + bộ lọc | Xem, tìm kiếm, đăng ký khóa miễn phí hoặc mua khóa trả phí |
| `/courses/:id` | Chi tiết khóa học | Đăng ký / mua khóa |
| `/my-courses` | Danh sách khóa đã đăng ký, % hoàn thành từng khóa | Bấm vào học |
| `/my-courses/:courseId/learn` | Giao diện học: video/tài liệu, sidebar danh sách bài, thanh tiến độ | Xem bài học, đánh dấu hoàn thành, ghi chú cá nhân |
| `/my-courses/:courseId/learn/:lessonId` | Nội dung bài học cụ thể (video, PDF, text) | Xem nội dung, đặt câu hỏi (comment), tải tài liệu nếu được phép |
| `/quizzes/:quizId` | Giao diện làm bài kiểm tra | Làm bài, nộp bài, xem kết quả (nếu GV cho phép xem đáp án) |
| `/assignments/:id` | Chi tiết bài tập | Nộp file / bài làm |
| `/grades` | Bảng điểm cá nhân: điểm từng bài kiểm tra, bài tập | Xem, tải xuống bảng điểm của mình |
| `/progress` | Biểu đồ tiến độ: % hoàn thành, thời gian học, streak | Xem |
| `/certificates` | Danh sách chứng chỉ đã đạt được | Xem, tải PDF chứng chỉ |
| `/leaderboard` | Bảng xếp hạng (nếu công khai) | Xem |
| `/forum` | Diễn đàn theo từng khóa đã đăng ký | Tạo bài đăng, bình luận, react |
| `/messages` | Hộp thư nhắn tin trực tiếp | Nhắn tin với GV của mình |
| `/notifications` | Danh sách thông báo | Xem, đánh dấu đã đọc |
| `/profile` | Hồ sơ cá nhân | Chỉnh sửa tên, avatar, mật khẩu, thông tin cá nhân |
| `/settings` | Cài đặt tài khoản | Bật/tắt thông báo email |

### Không thấy
- Menu quản trị, quản lý người dùng, tạo khóa học, báo cáo hệ thống
- Điểm của sinh viên khác
- Bài học của khóa chưa đăng ký (chỉ xem preview)

---

## 3. GIẢNG VIÊN (Instructor – đã đăng nhập)

### Layout
- Sidebar 2 khu vực: **Học tập** (giống SV) + **Giảng dạy** (riêng GV)

### Trang & chức năng
| Route | Nội dung hiển thị | Hành động được phép |
|---|---|---|
| `/dashboard` | Tổng quan: số học viên, doanh thu (nếu có), khóa học đang chạy, câu hỏi chờ trả lời | Xem |
| `/instructor/courses` | Danh sách khóa học của mình (bao gồm nháp, đã xuất bản, ẩn) | Tạo mới, chỉnh sửa, xóa, xuất bản / ẩn |
| `/instructor/courses/new` | Form tạo khóa học mới | Nhập tên, mô tả, danh mục, ảnh bìa, giá, cài đặt |
| `/instructor/courses/:id/edit` | Chỉnh sửa thông tin khóa học | Sửa thông tin tổng quan, cài đặt điều kiện mở khóa |
| `/instructor/courses/:id/curriculum` | Cấu trúc chương – bài: kéo thả sắp xếp | Thêm/sửa/xóa chương, thêm/sửa/xóa bài học, upload video/PDF/SCORM |
| `/instructor/courses/:id/students` | Danh sách SV đã đăng ký khóa | Xem, thêm SV thủ công, xóa SV, xem tiến độ từng người |
| `/instructor/courses/:id/reports` | Báo cáo khóa học: tỷ lệ hoàn thành, điểm trung bình, thời gian học | Xem, export CSV/PDF |
| `/instructor/quizzes` | Danh sách bài kiểm tra thuộc khóa của mình | Tạo, sửa, xóa quiz; quản lý ngân hàng câu hỏi |
| `/instructor/quizzes/:id/questions` | Danh sách câu hỏi | Thêm/sửa/xóa câu hỏi (trắc nghiệm, tự luận, kéo thả) |
| `/instructor/assignments` | Danh sách bài tập | Tạo bài tập, đặt deadline, chấm điểm thủ công, nhận xét |
| `/instructor/grades` | Bảng điểm toàn bộ SV trong khóa | Xem, chỉnh sửa điểm thủ công, export |
| `/instructor/certificates` | Cấu hình chứng chỉ cho khóa | Đặt điều kiện cấp (% hoàn thành, điểm tối thiểu), cấp / thu hồi thủ công |
| `/instructor/forum` | Diễn đàn trong khóa của mình | Đăng bài, trả lời, ghim bài, xóa bài của SV vi phạm |
| `/instructor/messages` | Hộp thư | Nhắn tin với SV trong lớp mình |
| `/instructor/live` | Quản lý live session | Tạo, lên lịch, bắt đầu/kết thúc live session (Zoom/Meet) |
| `/messages` | Tin nhắn trực tiếp | Nhắn tin với SV trong khóa của mình |
| `/profile` | Hồ sơ giảng viên | Chỉnh sửa bio, avatar, chuyên môn (hiển thị công khai) |

### Không thấy
- Quản lý người dùng toàn hệ thống
- Báo cáo toàn hệ thống
- Khóa học / bài học của GV khác (chỉ xem bản public)
- Cài đặt hệ thống

---

## 4. ADMIN (đã đăng nhập)

### Layout
- Sidebar đầy đủ: Dashboard, Người dùng, Khóa học, Nội dung, Kiểm tra, Báo cáo, Diễn đàn, Cài đặt

### Trang & chức năng
| Route | Nội dung hiển thị | Hành động được phép |
|---|---|---|
| `/admin/dashboard` | Tổng quan hệ thống: tổng user, khóa học, doanh thu, hoạt động gần đây | Xem |
| `/admin/users` | Danh sách toàn bộ người dùng, filter theo vai trò, trạng thái | Tạo, sửa, xóa, khoá / mở tài khoản, đổi vai trò |
| `/admin/users/:id` | Chi tiết người dùng: thông tin, lịch sử học, khóa đã đăng ký | Xem, chỉnh sửa, khoá tài khoản |
| `/admin/courses` | Toàn bộ khóa học (kể cả nháp của GV) | Xem, xuất bản/ẩn, xóa bất kỳ khóa |
| `/admin/courses/:id` | Chi tiết khóa học bất kỳ | Chỉnh sửa, xóa, chuyển GV phụ trách |
| `/admin/categories` | Quản lý danh mục / tag | Tạo, sửa, xóa danh mục |
| `/admin/quizzes` | Toàn bộ bài kiểm tra | Xem, sửa, xóa |
| `/admin/assignments` | Toàn bộ bài tập | Xem, chấm điểm, xóa |
| `/admin/grades` | Bảng điểm toàn hệ thống | Xem, chỉnh sửa, export |
| `/admin/certificates` | Quản lý chứng chỉ toàn hệ thống | Xem, cấp / thu hồi, chỉnh sửa mẫu chứng chỉ |
| `/admin/badges` | Quản lý huy hiệu (Badges) | Tạo, sửa, xóa, gán điều kiện nhận huy hiệu |
| `/admin/reports` | Báo cáo toàn hệ thống | Xem thống kê theo thời gian, export CSV/PDF |
| `/admin/reports/courses` | Báo cáo theo khóa học | Tỷ lệ hoàn thành, pass/fail, doanh thu |
| `/admin/reports/users` | Báo cáo theo người dùng | Hoạt động, tiến độ, điểm |
| `/admin/forum` | Toàn bộ diễn đàn | Xem, xóa, ghim bất kỳ bài đăng |
| `/admin/notifications` | Gửi thông báo hệ thống | Gửi thông báo đến tất cả / nhóm người dùng |
| `/admin/live` | Quản lý tất cả live session | Xem lịch, xóa, chỉnh sửa |
| `/admin/settings` | Cài đặt hệ thống | Cấu hình tên web, logo, màu sắc, email SMTP, tích hợp (Zoom, cổng thanh toán) |
| `/admin/settings/roles` | Cấu hình phân quyền | Chỉnh sửa quyền chi tiết của từng vai trò |
| `/admin/settings/payments` | Cài đặt thanh toán | Cấu hình Stripe, VNPay, tỷ lệ hoa hồng GV |

---

## Tổng hợp: Quyền truy cập theo route

| Route | Admin | GV | SV | Khách |
|---|:---:|:---:|:---:|:---:|
| `/` | ✅ | ✅ | ✅ | ✅ |
| `/courses` | ✅ | ✅ | ✅ | ✅ |
| `/courses/:id` | ✅ | ✅ | ✅ | ✅ (giới hạn) |
| `/login`, `/register` | redirect dashboard | redirect dashboard | redirect dashboard | ✅ |
| `/dashboard` | ✅ | ✅ | ✅ | ❌ |
| `/my-courses` | ❌ | ❌ | ✅ | ❌ |
| `/my-courses/:id/learn` | ❌ | ❌ | ✅ | ❌ |
| `/grades` | ❌ | ❌ | ✅ | ❌ |
| `/certificates` | ❌ | ❌ | ✅ | ❌ |
| `/instructor/*` | ❌ | ✅ | ❌ | ❌ |
| `/admin/*` | ✅ | ❌ | ❌ | ❌ |

---

## Ghi chú kỹ thuật cho agent

1. **Auth middleware**: Mọi route private cần kiểm tra JWT/session, decode role → redirect nếu không đủ quyền.
2. **Role enum**: `ADMIN | INSTRUCTOR | STUDENT | GUEST`
3. **Course ownership check**: GV chỉ được CRUD khóa có `instructorId === currentUser.id`.
4. **Enrollment check**: SV chỉ truy cập `/my-courses/:id/learn` nếu có bản ghi enrollment active.
5. **Preview lesson**: Bài học có flag `isFreePreview: true` → cho phép GUEST xem nội dung.
6. **Admin override**: Admin bypass tất cả ownership check.
7. **Redirect sau login**: Theo `role` → Admin: `/admin/dashboard`, GV: `/dashboard`, SV: `/dashboard`.
