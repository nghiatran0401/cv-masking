type MessageTree = {
  title: string;
  localOnly: string;
  maskedNotice: string;
  photoNotice: string;
  salary: string;
  salaryHelp: string;
  newBatch: string;
  start: string;
  drop: string;
  dropHelp: string;
  urlList: string;
  urlPaste: string;
  urlHelp: string;
  downloadLinks: string;
  downloadProgress: string;
  downloadFailed: string;
  browse: string;
  browseFolder: string;
  uploading: string;
  file: string;
  status: string;
  findings: string;
  hidden: string;
  actions: string;
  cancel: string;
  retry: string;
  remove: string;
  download: string;
  view: string;
  preview: string;
  closePreview: string;
  previewLoading: string;
  previewFailed: string;
  keep: string;
  deny: string;
  downloadAll: string;
  downloadAllHelp: string;
  downloadMasked: string;
  downloadMaskedHelp: string;
  noCvInFolder: string;
  empty: string;
  busy: string;
  retryMissing: string;
  residual: string;
  residualPage: string;
  unsafeOutput: string;
  sessionFailed: string;
  states: Record<string, string>;
  errors: Record<string, string>;
  reasons: Record<string, string>;
  entities: Record<string, string>;
  hiddenKinds: Record<string, string>;
};

export const MESSAGES: MessageTree = {
  title: "Che thông tin CV",
  localOnly: "Ứng dụng chỉ chạy trên máy này. CV không được gửi đi mạng.",
  maskedNotice:
    "Kết quả đã được che, không phải ẩn danh. Lịch sử làm việc vẫn có thể nhận ra người.",
  photoNotice: "Ảnh trong CV không được gỡ trong bản thử nghiệm này.",
  salary: "Che mức lương",
  salaryHelp:
    "Bật theo mặc định. Chỉ mục này có thể tắt; các mục bắt buộc luôn được che.",
  newBatch: "Lô mới",
  start: "Bắt đầu che",
  drop: "Kéo thả PDF hoặc DOCX vào đây",
  dropHelp: "Tối đa 50 tệp mỗi lô. Tên tệp chỉ hiện trên màn hình này.",
  urlList: "Danh sách liên kết CV",
  urlPaste: "Dán URL, mỗi dòng một liên kết",
  urlHelp:
    "Dán liên kết https từ máy chủ tệp công ty. Bấm Tải các liên kết để máy này tải các tệp và thêm vào lô. Liên kết phải mở được mà không cần đăng nhập trên trình duyệt. Máy này chỉ tải từ máy chủ tệp công ty và không gửi CV đi nơi khác.",
  downloadLinks: "Tải các liên kết",
  downloadProgress: "Đang tải {current}/{total}",
  downloadFailed: "Không tải được: {names}",
  browse: "Chọn tệp",
  browseFolder: "Chọn thư mục",
  uploading: "Đang tải lên",
  file: "Tệp",
  status: "Trạng thái",
  findings: "Số chỗ đã che",
  hidden: "Nội dung ẩn đã gỡ",
  actions: "Thao tác",
  cancel: "Hủy",
  retry: "Thử lại",
  remove: "Xóa",
  download: "Tải bản đã che",
  view: "Xem bản đã che",
  preview: "Bản đã che",
  closePreview: "Đóng",
  previewLoading: "Đang tải bản đã che…",
  previewFailed: "Không xem được. Tải xuống rồi mở bằng Preview.",
  keep: "Giữ",
  deny: "Xóa bản đã che",
  downloadAll: "Tải tất cả CV",
  downloadAllHelp:
    "Mỗi CV một thư mục, gồm tệp gốc và masked_. Gồm cả bản Cần xem. Không gồm lỗi không gỡ được nội dung ẩn. Chỉ chia sẻ tệp masked_ đã kiểm.",
  downloadMasked: "Chỉ tải CV đã che",
  downloadMaskedHelp:
    "Một thư mục, chỉ các tệp masked_. Gồm cả bản Cần xem. Không gồm lỗi không gỡ được nội dung ẩn. Chỉ chia sẻ tệp đã kiểm.",
  noCvInFolder: "Thư mục không có PDF hoặc DOCX.",
  empty: "Chưa có tệp.",
  busy: "Đang xử lý…",
  retryMissing:
    "Tệp không còn trên màn hình này. Giữ tab này mở khi bấm Thử lại.",
  residual: "Còn sót, không chia sẻ:",
  residualPage: "trang",
  unsafeOutput: "Bản này chưa an toàn để gửi. Chỉ xem để biết chỗ còn sót.",
  sessionFailed: "Không mở được phiên làm việc. Tải lại trang.",
  states: {
    created: "Đang nhận",
    uploaded: "Đã nhận",
    validating: "Đang kiểm tra",
    queued: "Trong hàng chờ",
    processing: "Đang che",
    verifying: "Đang đối chiếu",
    review_required: "Cần xem",
    completed: "Hoàn tất",
    failed: "Lỗi",
    rejected: "Đã từ chối",
    cancelled: "Đã hủy",
  },
  errors: {
    UPLOAD_UNSUPPORTED_TYPE: "Không phải PDF hoặc DOCX.",
    UPLOAD_SPOOFED_TYPE: "Phần mở rộng không khớp nội dung tệp.",
    DOCX_MACRO_OR_TEMPLATE: "Không nhận tệp macro hoặc mẫu Word.",
    UPLOAD_FILE_TOO_LARGE: "Tệp vượt giới hạn dung lượng.",
    UPLOAD_BATCH_FILE_LIMIT: "Lô đã đủ số tệp tối đa.",
    UPLOAD_BATCH_SIZE_LIMIT: "Lô đã đủ dung lượng tối đa.",
    UPLOAD_DUPLICATE: "Tệp trùng với một tệp khác trong lô.",
    UPLOAD_MALFORMED_REQUEST: "Yêu cầu tải lên không hợp lệ. Thử lại.",
    UPLOAD_SOURCE_UNAVAILABLE:
      "Không tải được liên kết từ máy chủ tệp. Liên kết có thể cần đăng nhập trình duyệt. Bấm Tải các liên kết để thử lại.",
    UPLOAD_TIMEOUT: "Tải lên quá thời gian. Thử lại.",
    UPLOAD_BATCH_CLOSED: "Lô không còn nhận tệp mới.",
    PDF_MALFORMED: "PDF không đọc được.",
    PDF_NO_PAGES: "PDF không có trang.",
    PDF_RESOURCE_LIMIT: "PDF vượt giới hạn tài nguyên.",
    DOCX_MALFORMED: "DOCX không đọc được.",
    DOCX_UNSAFE_ARCHIVE: "DOCX có đường dẫn không an toàn.",
    DOCX_RESOURCE_LIMIT: "DOCX vượt giới hạn tài nguyên.",
    DETECT_FAILED: "Không phát hiện được thông tin cần che.",
    MAP_FAILED: "Không gán được vị trí cần che.",
    REDACT_FAILED: "Không che được nội dung. Thử lại.",
    REDACT_SANITIZE_FAILED: "Không gỡ được siêu dữ liệu hoặc nội dung ẩn.",
    REDACT_OUTPUT_WRITE_FAILED: "Không ghi được tệp kết quả. Thử lại.",
    VERIFY_OUTPUT_INVALID: "Tệp kết quả không mở được.",
    VERIFY_PAGE_COUNT_MISMATCH: "Số trang kết quả khác bản gốc.",
    VERIFY_STRUCTURE_MISMATCH: "Cấu trúc DOCX kết quả không khớp.",
    VERIFY_RESIDUAL_FINDING: "Vẫn còn thông tin cần che trong kết quả.",
    VERIFY_RESIDUAL_DETECTION: "Đối chiếu vẫn thấy thông tin cần che.",
    VERIFY_RESIDUAL_METADATA: "Vẫn còn siêu dữ liệu hoặc nội dung ẩn.",
    JOB_TIMEOUT: "Xử lý quá thời gian.",
    JOB_CANCELLED: "Đã hủy.",
    JOB_INTERRUPTED: "Ứng dụng dừng giữa chừng. Bấm Thử lại.",
    STORAGE_WRITE_FAILED: "Không ghi được đĩa. Thử lại.",
    STORAGE_PATH_REJECTED: "Đường lưu trữ không hợp lệ.",
    STORAGE_INTEGRITY_FAILED: "Tệp lưu trữ bị đổi.",
    INTERNAL_ERROR: "Lỗi nội bộ.",
    SECURITY_HOST_REJECTED: "Yêu cầu không đến từ máy này.",
    SECURITY_ORIGIN_REJECTED: "Nguồn yêu cầu không được phép.",
    SECURITY_TOKEN_INVALID: "Phiên làm việc hết hạn. Tải lại trang.",
    SECURITY_RATE_LIMITED: "Quá nhiều yêu cầu. Đợi rồi thử lại.",
  },
  reasons: {
    PDF_ENCRYPTED: "PDF đang khóa mật khẩu.",
    PDF_TOO_MANY_PAGES: "PDF vượt số trang cho phép.",
    PDF_NO_TEXT_LAYER: "Trang chỉ là ảnh, không có lớp chữ.",
    PDF_TEXT_UNRELIABLE: "Chữ trong PDF không đọc tin cậy.",
    DOCX_ENCRYPTED: "DOCX đang khóa mật khẩu.",
    DOCX_TOO_LARGE_TEXT: "Lượng chữ vượt giới hạn.",
    DOCX_NO_TEXT: "Không có chữ để che.",
    DETECT_LOW_CONFIDENCE: "Một số chỗ che chưa chắc, hãy mở bản đã che.",
    DETECT_NO_CANDIDATE_NAME: "Không thấy tên ứng viên; kiểm tra bản đã che.",
    MAP_AMBIGUOUS: "Một chỗ che nằm chồng chữ; hãy kiểm tra bản đã che.",
    VERIFY_REVIEW: "Đối chiếu không quyết được; chỉ được xóa bản đã che.",
  },
  entities: {
    candidate_name: "Tên ứng viên",
    reference_name: "Tên người tham chiếu",
    email: "Email",
    phone: "Điện thoại",
    national_id: "CCCD/CMND",
    passport: "Hộ chiếu",
    postal_address: "Địa chỉ",
    date_of_birth: "Ngày sinh",
    gender: "Giới tính",
    marital_status: "Tình trạng hôn nhân",
    nationality: "Quốc tịch",
    religion: "Tôn giáo",
    ethnicity: "Dân tộc",
    health: "Sức khỏe",
    family_details: "Gia đình",
    personal_url: "Liên kết cá nhân",
    salary: "Lương",
  },
  hiddenKinds: {
    embedded_files: "Tệp đính kèm",
    forms: "Biểu mẫu",
    javascript: "JavaScript",
    annotations: "Chú thích",
    optional_content: "Lớp ẩn",
    invisible_text: "Chữ vô hình",
    tracked_changes: "Thay đổi theo dõi",
    comments: "Bình luận",
    hidden_text: "Chữ ẩn",
    imported_chunks: "Đoạn nhập",
    custom_xml: "XML tùy chỉnh",
    glossary: "Glossary",
    external_relationships: "Liên kết ngoài",
  },
};

export function messageForCode(code: string): string {
  return MESSAGES.errors[code] ?? code;
}

export function messageForReason(reason: string): string {
  return MESSAGES.reasons[reason] ?? reason;
}

export function messageForState(state: string): string {
  return MESSAGES.states[state] ?? state;
}
