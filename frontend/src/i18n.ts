export type Language = "vi" | "en";

export const LANGUAGE_KEY = "cv-masking-language";

type MessageTree = {
  title: string;
  localOnly: string;
  maskedNotice: string;
  photoNotice: string;
  language: string;
  vietnamese: string;
  english: string;
  salary: string;
  salaryHelp: string;
  newBatch: string;
  start: string;
  purge: string;
  drop: string;
  dropHelp: string;
  browse: string;
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

export const MESSAGES: Record<Language, MessageTree> = {
  vi: {
    title: "Che thông tin CV",
    localOnly: "Ứng dụng chỉ chạy trên máy này. CV không được gửi đi mạng.",
    maskedNotice:
      "Kết quả đã được che, không phải ẩn danh. Lịch sử làm việc vẫn có thể nhận ra người.",
    photoNotice: "Ảnh trong CV không được gỡ trong bản thử nghiệm này.",
    language: "Ngôn ngữ",
    vietnamese: "Tiếng Việt",
    english: "English",
    salary: "Che mức lương",
    salaryHelp:
      "Bật theo mặc định. Chỉ mục này có thể tắt; các mục bắt buộc luôn được che.",
    newBatch: "Lô mới",
    start: "Bắt đầu che",
    purge: "Xóa lô này",
    drop: "Kéo thả PDF hoặc DOCX vào đây",
    dropHelp: "Tối đa 50 tệp mỗi lô. Tên tệp chỉ hiện trên màn hình này.",
    browse: "Chọn tệp",
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
    downloadAll: "Tải tất cả CV đã che",
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
  },
  en: {
    title: "CV masking",
    localOnly:
      "This app runs only on this computer. CVs are not sent to any network.",
    maskedNotice:
      "Output is masked, not anonymized. Career history can still identify a person.",
    photoNotice: "Photos in the CV are not removed in this proof of concept.",
    language: "Language",
    vietnamese: "Tiếng Việt",
    english: "English",
    salary: "Mask salary",
    salaryHelp:
      "On by default. This is the only optional item; mandatory items cannot be turned off.",
    newBatch: "New batch",
    start: "Start masking",
    purge: "Delete this batch",
    drop: "Drop PDF or DOCX files here",
    dropHelp: "Up to 50 files per batch. File names stay on this screen only.",
    browse: "Choose files",
    uploading: "Uploading",
    file: "File",
    status: "Status",
    findings: "Masked counts",
    hidden: "Hidden content removed",
    actions: "Actions",
    cancel: "Cancel",
    retry: "Retry",
    remove: "Remove",
    download: "Download masked file",
    view: "View masked file",
    preview: "Masked file",
    closePreview: "Close",
    previewLoading: "Loading masked file…",
    previewFailed: "Could not preview. Download and open it in Preview.",
    keep: "Keep",
    deny: "Delete masked file",
    downloadAll: "Download all masked CVs",
    empty: "No files yet.",
    busy: "Processing…",
    retryMissing:
      "The file is no longer in this tab. Keep this tab open when you click Retry.",
    residual: "Still unmasked, do not share:",
    residualPage: "page",
    unsafeOutput:
      "This file is not safe to send. View it only to see what remains.",
    sessionFailed: "Could not open a session. Reload the page.",
    states: {
      created: "Receiving",
      uploaded: "Uploaded",
      validating: "Checking",
      queued: "Queued",
      processing: "Masking",
      verifying: "Verifying",
      review_required: "Needs review",
      completed: "Completed",
      failed: "Failed",
      rejected: "Rejected",
      cancelled: "Cancelled",
    },
    errors: {
      UPLOAD_UNSUPPORTED_TYPE: "Not a PDF or DOCX.",
      UPLOAD_SPOOFED_TYPE: "The extension does not match the file contents.",
      DOCX_MACRO_OR_TEMPLATE:
        "Macro-enabled or template Word files are refused.",
      UPLOAD_FILE_TOO_LARGE: "The file exceeds the size limit.",
      UPLOAD_BATCH_FILE_LIMIT:
        "The batch already has the maximum number of files.",
      UPLOAD_BATCH_SIZE_LIMIT: "The batch already has the maximum total size.",
      UPLOAD_DUPLICATE: "This file is already in the batch.",
      UPLOAD_MALFORMED_REQUEST: "The upload request was invalid. Try again.",
      UPLOAD_TIMEOUT: "The upload timed out. Try again.",
      UPLOAD_BATCH_CLOSED: "The batch is no longer accepting files.",
      PDF_MALFORMED: "The PDF could not be parsed.",
      PDF_NO_PAGES: "The PDF has no pages.",
      PDF_RESOURCE_LIMIT: "The PDF exceeded resource limits.",
      DOCX_MALFORMED: "The DOCX could not be parsed.",
      DOCX_UNSAFE_ARCHIVE: "The DOCX has an unsafe entry name.",
      DOCX_RESOURCE_LIMIT: "The DOCX exceeded resource limits.",
      DETECT_FAILED: "Detection could not run.",
      MAP_FAILED: "A finding could not be placed on the page.",
      REDACT_FAILED: "Redaction could not be applied. Try again.",
      REDACT_SANITIZE_FAILED:
        "Metadata or hidden content could not be removed.",
      REDACT_OUTPUT_WRITE_FAILED: "The output could not be stored. Try again.",
      VERIFY_OUTPUT_INVALID: "The output could not be opened.",
      VERIFY_PAGE_COUNT_MISMATCH:
        "The output page count differs from the input.",
      VERIFY_STRUCTURE_MISMATCH: "The output DOCX structure does not match.",
      VERIFY_RESIDUAL_FINDING: "A source finding is still extractable.",
      VERIFY_RESIDUAL_DETECTION:
        "A detector still found entities in the output.",
      VERIFY_RESIDUAL_METADATA: "Metadata or hidden content remains.",
      JOB_TIMEOUT: "Processing exceeded the time limit.",
      JOB_CANCELLED: "Cancelled.",
      JOB_INTERRUPTED: "The app stopped mid-document. Click Retry.",
      STORAGE_WRITE_FAILED: "A local write failed. Try again.",
      STORAGE_PATH_REJECTED: "The storage path was refused.",
      STORAGE_INTEGRITY_FAILED: "A stored file no longer matches its hash.",
      INTERNAL_ERROR: "An internal error occurred.",
      SECURITY_HOST_REJECTED: "The request did not come from this computer.",
      SECURITY_ORIGIN_REJECTED: "The request origin is not allowed.",
      SECURITY_TOKEN_INVALID: "The session expired. Reload the page.",
      SECURITY_RATE_LIMITED: "Too many requests. Wait and try again.",
    },
    reasons: {
      PDF_ENCRYPTED: "The PDF is password-protected.",
      PDF_TOO_MANY_PAGES: "The PDF exceeds the page limit.",
      PDF_NO_TEXT_LAYER: "At least one page is image-only.",
      PDF_TEXT_UNRELIABLE: "The PDF text cannot be mapped reliably.",
      DOCX_ENCRYPTED: "The DOCX is password-protected.",
      DOCX_TOO_LARGE_TEXT: "Extracted text exceeds the length limit.",
      DOCX_NO_TEXT: "No extractable text.",
      DETECT_LOW_CONFIDENCE: "Some findings need a check of the masked file.",
      DETECT_NO_CANDIDATE_NAME:
        "No candidate name was found; check the masked file.",
      MAP_AMBIGUOUS:
        "A finding overlapped another word; check the masked file.",
      VERIFY_REVIEW:
        "The verifier could not decide; the masked file can only be deleted.",
    },
    entities: {
      candidate_name: "Candidate name",
      reference_name: "Reference name",
      email: "Email",
      phone: "Phone",
      national_id: "National ID",
      passport: "Passport",
      postal_address: "Address",
      date_of_birth: "Date of birth",
      gender: "Gender",
      marital_status: "Marital status",
      nationality: "Nationality",
      religion: "Religion",
      ethnicity: "Ethnicity",
      health: "Health",
      family_details: "Family",
      personal_url: "Personal URL",
      salary: "Salary",
    },
    hiddenKinds: {
      embedded_files: "Embedded files",
      forms: "Forms",
      javascript: "JavaScript",
      annotations: "Annotations",
      optional_content: "Optional content",
      invisible_text: "Invisible text",
      tracked_changes: "Tracked changes",
      comments: "Comments",
      hidden_text: "Hidden text",
      imported_chunks: "Imported chunks",
      custom_xml: "Custom XML",
      glossary: "Glossary",
      external_relationships: "External relationships",
    },
  },
};

export function loadLanguage(): Language {
  try {
    const stored = sessionStorage.getItem(LANGUAGE_KEY);
    if (stored === "en" || stored === "vi") {
      return stored;
    }
  } catch {
    return "vi";
  }
  return "vi";
}

export function saveLanguage(language: Language): void {
  try {
    sessionStorage.setItem(LANGUAGE_KEY, language);
  } catch {
    return;
  }
}

export function messageForCode(language: Language, code: string): string {
  return MESSAGES[language].errors[code] ?? code;
}

export function messageForReason(language: Language, reason: string): string {
  return MESSAGES[language].reasons[reason] ?? reason;
}

export function messageForState(language: Language, state: string): string {
  return MESSAGES[language].states[state] ?? state;
}
