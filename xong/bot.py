import logging
import json
import asyncio
import datetime
from telegram import Update, Bot
from telegram.ext import (
    ApplicationBuilder, 
    ContextTypes, 
    CommandHandler, 
    MessageHandler, 
    filters,
)
from telegram import ReplyKeyboardMarkup, KeyboardButton

# Thiết lập Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)

# THÔNG TIN BOT VÀ GROUP CỦA BẠN
TOKEN = "8426449907:AAGJOf65O3a5jwbq6E1PidWaW0WYZorLybo"
# Đặt tên groups (Dùng ID hoặc @username) để bot kiểm tra
GROUPS = {
    "@cpbankgiaitri":"", 
    "@cpbankphatcode":"",
    "@cpbankkenhchat":"",
    "@cpbankclub":"",
    "@CHATCPBANK":"",
}

# --- CẤU HÌNH ADMIN ---
ADMIN_ID = 7730389009 

# --- HẰNG SỐ CỦA HỆ THỐNG GIỚI THIỆU VÀ RÚT CODE ---
USER_DATA_FILE = 'user_data.json'
CODES_FILE = 'codes.json' 
REWARD_AMOUNT = 2000
MIN_CODE_VALUE = 10000       # Mệnh giá code duy nhất mà bot sử dụng
MIN_WITHDRAWAL_AMOUNT = 10000 # Số dư tối thiểu để rút

# --- CÁC HÀM QUẢN LÝ DỮ LIỆU NGƯỜI DÙNG VÀ CODES ---

def load_user_data_file() -> dict:
    """Tải toàn bộ dữ liệu người dùng từ file JSON."""
    try:
        with open(USER_DATA_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            return json.loads(content) if content else {}
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        logging.error("Lỗi đọc file user_data.json. Trả về dữ liệu rỗng.")
        return {}

def save_user_data_file(data: dict) -> None:
    """Lưu toàn bộ dữ liệu người dùng vào file JSON."""
    try:
        with open(USER_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Lỗi khi lưu user_data.json: {e}")

def get_user_data(user_id: int, user_data_all: dict) -> dict:
    """Lấy dữ liệu của một người dùng, nếu chưa có thì khởi tạo."""
    user_id_str = str(user_id)
    if user_id_str not in user_data_all:
        user_data_all[user_id_str] = {
            "balance": 0,
            "referred_by": None,
            "is_reward_paid": False
        }
    return user_data_all[user_id_str]
    
def load_codes_file() -> dict:
    """Tải kho code từ file JSON."""
    try:
        with open(CODES_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
            return json.loads(content) if content else {"available": [], "used": []}
    except FileNotFoundError:
        logging.error(f"Không tìm thấy file {CODES_FILE}. Vui lòng tạo file.")
        return {"available": [], "used": []}
    except json.JSONDecodeError:
        logging.error(f"Lỗi đọc file {CODES_FILE}. Dữ liệu code bị lỗi.")
        return {"available": [], "used": []}

def save_codes_file(data: dict) -> None:
    """Lưu kho code vào file JSON."""
    try:
        with open(CODES_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
    except Exception as e:
        logging.error(f"Lỗi khi lưu {CODES_FILE}: {e}")

# --- LOGIC RÚT CODE MỚI ---

def process_code_withdrawal(user_id: int, target_user: str, amount: int, codes_data: dict, user_data_all: dict) -> tuple[bool, str, list]:
    """
    Thực hiện giao dịch rút code, hỗ trợ tách code 10000 VNĐ.

    Trả về: (thành công, thông báo lỗi/thông báo thành công, danh sách codes đã rút)
    """
    
    # 1. Kiểm tra bội số của 10000
    if amount % MIN_CODE_VALUE != 0:
        return False, f"❌ **Lỗi:** Số tiền rút phải là bội số của **{MIN_CODE_VALUE} VNĐ** (ví dụ: 10000, 20000, 30000...).", []
        
    num_codes_needed = amount // MIN_CODE_VALUE
    
    # 2. Kiểm tra số lượng code có sẵn
    if len(codes_data["available"]) < num_codes_needed:
        return False, f"❌ **Lỗi:** Kho code **{MIN_CODE_VALUE} VNĐ** không đủ. Cần {num_codes_needed} code nhưng chỉ còn {len(codes_data['available'])} code. Vui lòng liên hệ CSKH.", []

    # Bắt đầu giao dịch
    
    # 3. Trừ tiền người dùng
    user_id_str = str(user_id)
    
    # === BỔ SUNG: BẢO VỆ OVERDRAFT/RACE CONDITION (CHỈ THÊM) ===
    current_balance_check = user_data_all.get(user_id_str, {}).get("balance", 0)
    if current_balance_check < amount:
        # Nếu số dư không đủ ngay trước khi trừ, hủy giao dịch
        return False, "❌ **Lỗi bảo mật:** Số dư của bạn không đủ để thực hiện giao dịch này. Đã có lỗi xảy ra.", []
    # === KẾT THÚC BỔ SUNG ===
    
    user_data_all[user_id_str]["balance"] -= amount
    
    # 4. Chọn và chuyển code sang 'used'
    codes_to_transfer = codes_data["available"][:num_codes_needed]
    codes_data["available"] = codes_data["available"][num_codes_needed:]
    
    # 5. Ghi nhận vào log codes đã dùng
    used_entry = {
        "codes": codes_to_transfer,
        "total_amount": amount,
        "user_id": user_id,
        "target_user": target_user,
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    codes_data["used"].append(used_entry)

    # 6. Lưu dữ liệu
    save_user_data_file(user_data_all)
    save_codes_file(codes_data)

    return True, "", codes_to_transfer

# --- CÁC HÀM TIỆN ÍCH ---

# Hàm kiểm tra User có phải Admin không
def is_admin(user_id: int) -> bool:
    """Kiểm tra xem User ID có phải là ID Admin đã cấu hình không."""
    return user_id == ADMIN_ID

# Hàm kiểm tra thành viên đã tham gia các nhóm yêu cầu chưa
async def check_user_joined_contact_bot(bot: Bot, user_id: int) -> dict:
    results = {}
    for group, name in GROUPS.items():
        try:
            member = await bot.get_chat_member(group, user_id)
            if member.status in ['member', 'administrator', 'creator']:
                results[group] = True
            else:
                results[group] = False
        except Exception as e:
            logging.error(f"Lỗi khi kiểm tra group {group}: {e}")
            results[group] = False
    return results

# --- CÁC KEYBOARD ---

main_keyboard = ReplyKeyboardMarkup(
    [
        [KeyboardButton("💰 Số dư của tôi")],
        [
            KeyboardButton("🎁 Rút code"),
            KeyboardButton("💎 Mời bạn bè")
        ],
        [
            KeyboardButton("🎮 Link Game"),
            KeyboardButton("☎️ CSKH Hỗ Trợ")
        ]
    ],
    resize_keyboard=True,
    one_time_keyboard=False
)

# --- HÀM XỬ LÝ LỆNH ADMIN ĐỂ CỘNG TIỀN ---

async def admin_add_balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # --- BỔ SUNG: BỎ QUA TIN NHẮN TỪ GROUP ---
    if update.message and update.message.chat.type != 'private':
        return
    # ----------------------------------------
    user_id = update.effective_user.id
    
    # 1. KIỂM TRA QUYỀN ADMIN
    if not is_admin(user_id):
        await update.message.reply_text("❌ **Lỗi:** Bạn không có quyền Admin để sử dụng lệnh này.", parse_mode='Markdown')
        return
        
    # 2. KIỂM TRA CÚ PHÁP
    if len(context.args) != 2:
        await update.message.reply_text(
            "⚠️ **Sai cú pháp!**\nSử dụng: `/admin_add <Target_User_ID> <Số_Tiền_Cần_Cộng>`\nVí dụ: `/admin_add 123456789 50000`", 
            parse_mode='Markdown'
        )
        return
    
    # 3. PHÂN TÍCH THAM SỐ
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ **Lỗi:** ID người dùng phải là một chuỗi số.", parse_mode='Markdown')
        return

    try:
        amount_to_add = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ **Lỗi:** Số tiền cộng phải là một số nguyên dương.", parse_mode='Markdown')
        return

    if amount_to_add <= 0:
        await update.message.reply_text("❌ **Lỗi:** Số tiền cộng phải lớn hơn 0.", parse_mode='Markdown')
        return

    # 4. THỰC HIỆN CỘNG TIỀN
    user_data_all = load_user_data_file()
    target_user_data = get_user_data(target_id, user_data_all)
    
    target_user_data["balance"] += amount_to_add
    
    # Lưu thay đổi vào file
    save_user_data_file(user_data_all)

    # 5. THÔNG BÁO KẾT QUẢ
    
    # Thông báo cho Admin
    success_message = (
        f"✅ **CỘNG TIỀN THÀNH CÔNG!**\n\n"
        f"Đã cộng **{amount_to_add} VNĐ** vào ID: **{target_id}**\n"
        f"Số dư mới của họ: **{target_user_data['balance']} VNĐ**"
    )
    await update.message.reply_text(success_message, parse_mode='Markdown')
    
    # Thông báo cho người được cộng tiền (tùy chọn)
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"💵 **Thông báo Admin:** Tài khoản của bạn vừa được cộng thêm **{amount_to_add} VNĐ**.\nSố dư hiện tại: **{target_user_data['balance']} VNĐ**",
            parse_mode='Markdown'
        )
    except Exception:
        logging.warning(f"Không thể gửi thông báo tới user {target_id}.")

# --- HẾT HÀM ADMIN ADD BALANCE ---


# --- HÀM XỬ LÝ LỆNH ADMIN ĐỂ TRA CỨU NGƯỜI DÙNG (MỚI) ---

async def admin_check_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # --- BỔ SUNG: BỎ QUA TIN NHẮN TỪ GROUP ---
    if update.message and update.message.chat.type != 'private':
        return
    # ----------------------------------------
    user_id = update.effective_user.id
    
    # 1. KIỂM TRA QUYỀN ADMIN
    if not is_admin(user_id):
        await update.message.reply_text("❌ **Lỗi:** Bạn không có quyền Admin để sử dụng lệnh này.", parse_mode='Markdown')
        return
        
    # 2. KIỂM TRA CÚ PHÁP
    if len(context.args) != 1:
        await update.message.reply_text(
            "⚠️ **Sai cú pháp!**\nSử dụng: `/admin_check <Target_User_ID>`\nVí dụ: `/admin_check 987654321`", 
            parse_mode='Markdown'
        )
        return
    
    # 3. PHÂN TÍCH THAM SỐ
    try:
        target_id_str = context.args[0]
        target_id = int(target_id_str)
    except ValueError:
        await update.message.reply_text("❌ **Lỗi:** ID người dùng phải là một chuỗi số.", parse_mode='Markdown')
        return

    # 4. TẢI DỮ LIỆU
    user_data_all = load_user_data_file()
    
    if target_id_str not in user_data_all:
        await update.message.reply_text(f"❌ **Lỗi:** Không tìm thấy dữ liệu người dùng với ID: **{target_id_str}**.", parse_mode='Markdown')
        return

    # 5. HIỂN THỊ THÔNG TIN
    target_user_data = user_data_all[target_id_str]
    
    referred_by = target_user_data.get("referred_by")
    is_reward_paid = target_user_data.get("is_reward_paid", False)

    # Định dạng lại thông tin để dễ đọc
    referred_by_text = f"Đã được giới thiệu bởi ID: `{referred_by}`" if referred_by else "Không có người giới thiệu"
    reward_status_text = "✅ Đã nhận thưởng 2000 VNĐ" if is_reward_paid else "❌ Chưa nhận thưởng giới thiệu"

    response_message = (
        f"📝 **THÔNG TIN NGƯỜI DÙNG ID: {target_id_str}**\n\n"
        f"💰 **Số dư hiện tại:** **{target_user_data['balance']} VNĐ**\n"
        f"🔗 **Trạng thái giới thiệu:** {referred_by_text}\n"
        f"🎁 **Trạng thái thưởng:** {reward_status_text}"
    )
    
    await update.message.reply_text(response_message, parse_mode='Markdown')

# --- HẾT HÀM ADMIN CHECK USER ---


# --- HÀM XỬ LÝ LỆNH RÚT CODE (/rutcode) ---

async def rutcode_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # --- BỔ SUNG: BỎ QUA TIN NHẮN TỪ GROUP ---
    if update.message and update.message.chat.type != 'private':
        return
    # ----------------------------------------
    user_id = update.effective_user.id
    
    # 1. Kiểm tra cú pháp
    if len(context.args) != 2:
        await update.message.reply_text(
            "⚠️ **Sai cú pháp!**\nSử dụng: `/rutcode [ID TELE OR TNV] [SỐ TIỀN]`\nVí dụ: `/rutcode mytelegramusername 24000`\n(Số tiền phải là bội số của 12000 VNĐ)", 
            parse_mode='Markdown'
        )
        return

    target_user = context.args[0]
    try:
        amount_to_withdraw = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ **Lỗi:** Số tiền rút phải là một số nguyên dương.")
        return

    # === BỔ SUNG: BẢO VỆ ĐẦU VÀO ÂM/BẰNG KHÔNG (CHỈ THÊM) ===
    if amount_to_withdraw <= 0:
        await update.message.reply_text("❌ **Lỗi:** Số tiền rút phải lớn hơn 0.", parse_mode='Markdown')
        return
    # === KẾT THÚC BỔ SUNG ===
    
    # 2. Tải dữ liệu và kiểm tra số dư
    user_data_all = load_user_data_file()
    user_data = get_user_data(user_id, user_data_all)
    current_balance = user_data["balance"]

    if current_balance < MIN_WITHDRAWAL_AMOUNT:
        await update.message.reply_text(f"❌ **Lỗi:** Số dư tối thiểu để rút là **{MIN_WITHDRAWAL_AMOUNT} VNĐ**. Số dư hiện tại: **{current_balance} VNĐ**.", parse_mode='Markdown')
        return

    if current_balance < amount_to_withdraw:
        await update.message.reply_text(f"❌ **Lỗi:** Số dư của bạn (**{current_balance} VNĐ**) không đủ để rút **{amount_to_withdraw} VNĐ**.", parse_mode='Markdown')
        return

    # 3. Thực hiện giao dịch rút code
    codes_data = load_codes_file()
    
    success, message, codes_list = process_code_withdrawal(
        user_id, 
        target_user, 
        amount_to_withdraw, 
        codes_data, 
        user_data_all
    )

    if success:
        # 4. Thông báo kết quả thành công
        codes_str = "\n".join([f"`{c}`" for c in codes_list])
        
        success_message = (
            f"✅ **RÚT CODE THÀNH CÔNG!** ✅\n\n"
            f"Bạn đã rút thành công **{amount_to_withdraw} VNĐ** (tương đương {len(codes_list)} code).\n"
            f"Số dư mới: **{user_data_all[str(user_id)]['balance']} VNĐ**\n\n"
            f"Mã code của bạn (Mệnh giá {MIN_CODE_VALUE} VNĐ/Code): \n"
            f"{codes_str}\n\n"
            f"Vui lòng sử dụng code này cho tài khoản: **{target_user}**"
        )
        await update.message.reply_text(success_message, parse_mode='Markdown')
    else:
        # 4. Thông báo lỗi
        await update.message.reply_text(message, parse_mode='Markdown')


# HÀM XỬ LÝ LỆNH /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # --- BỔ SUNG: BỎ QUA TIN NHẮN TỪ GROUP ---
    if update.message and update.message.chat.type != 'private':
        return
    # ----------------------------------------
    user_id = update.effective_user.id
    
    # 1. Xử lý tham số giới thiệu (Referral parameter)
    referrer_id = None
    if context.args:
        start_payload = context.args[0]
        if start_payload.startswith('ref') and start_payload[3:].isdigit():
            referrer_id = int(start_payload[3:])
            if referrer_id == user_id:
                referrer_id = None 

    # 2. Tải data người dùng và cấu hình
    try:
        with open('data.json', 'r', encoding='utf-8') as f:
            data_load = json.load(f)
    except FileNotFoundError:
        # Lỗi này chỉ xảy ra nếu file data.json không tồn tại
        await update.message.reply_text("Lỗi: Không tìm thấy file data.json.")
        return
    
    # LOGIC: TẢI DATA NGƯỜI DÙNG VÀ XỬ LÝ THƯỞNG
    user_data_all = load_user_data_file()
    user_data = get_user_data(user_id, user_data_all)
    
    is_data_changed = False
    # Gán referrer_id nếu có và user này chưa được gán trước đó
    if referrer_id and user_data["referred_by"] is None:
        user_data["referred_by"] = referrer_id
        is_data_changed = True

    text = f"Xin chào **{update.effective_user.first_name}**! Vui lòng sử dụng các nút bên dưới."
    
    check = await check_user_joined_contact_bot(context.bot, user_id)
    
    if all(check.values()):
        # Nếu đã là thành viên (xác thực đầy đủ)
        
        # LOGIC THƯỞNG 2000 VNĐ: Nếu người này được giới thiệu VÀ chưa được thưởng
        if user_data["referred_by"] is not None and user_data["is_reward_paid"] is False:
            
            ref_id = user_data["referred_by"]
            referrer_data = get_user_data(ref_id, user_data_all)
            referrer_data["balance"] += REWARD_AMOUNT # Cộng 2000 VNĐ
            
            user_data["is_reward_paid"] = True
            is_data_changed = True
            
            # Lưu lại sự thay đổi vào user_data.json
            save_user_data_file(user_data_all) 

            # Thông báo cho người mới
            await update.message.reply_text(
                f"🎉 Chúc mừng! Bạn đã xác thực thành công. Bot đã cộng **{REWARD_AMOUNT} VNĐ** cho người mời bạn (ID: {ref_id}).", 
                reply_markup=main_keyboard, 
                parse_mode='Markdown'
            )
            # Tùy chọn: Gửi tin nhắn thông báo cho người mời
            try:
                await context.bot.send_message(
                    chat_id=ref_id, 
                    text=f"🎁 Chúc mừng! Tài khoản **{update.effective_user.first_name}** đã xác thực thành công qua link mời của bạn.\nBạn được cộng **{REWARD_AMOUNT} VNĐ** vào số dư!",
                    parse_mode='Markdown'
                )
            except Exception as e:
                logging.warning(f"Không thể gửi thông báo cho referrer {ref_id}: {e}")
        
        elif referrer_id:
             await update.message.reply_text("Chào mừng bạn quay lại!", reply_markup=main_keyboard, parse_mode='Markdown')
        
        else:
            await update.message.reply_text(text, reply_markup=main_keyboard, parse_mode='Markdown')
            
        if is_data_changed and user_data["is_reward_paid"] is False:
             save_user_data_file(user_data_all)

    else:
        # Nếu chưa là thành viên, yêu cầu tham gia các kênh
        msg = "⛔️ Bạn chưa tham gia đủ các nhóm của bot. Vui lòng tham gia các nhóm sau:\n"
        for group, is_joined in check.items():
            if not is_joined:
                msg += f"• [{group}]({group})\n" 
        
        await update.message.reply_text(msg + "\nSau khi tham gia, hãy nhấn **/start** lại để tiếp tục.", parse_mode='Markdown', disable_web_page_preview=True)
        
        if is_data_changed:
            save_user_data_file(user_data_all)


# HÀM XỬ LÝ CÁC NÚT BẤM (BUTTONS)
async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # --- BỔ SUNG: BỎ QUA TIN NHẮN TỪ GROUP ---
    if update.message and update.message.chat.type != 'private':
        return
    # ----------------------------------------
    user_id = update.effective_user.id
    text = update.message.text
    
    # Tải data cấu hình
    try:
        with open('data.json', 'r', encoding='utf-8') as f:
            data_load = json.load(f)
    except FileNotFoundError:
        await update.message.reply_text("Lỗi: Không tìm thấy file data.json.")
        return

    # LOGIC: TẢI DATA NGƯỜI DÙNG
    user_data_all = load_user_data_file()
    user_data = get_user_data(user_id, user_data_all)

    # Kiểm tra tư cách thành viên trước khi xử lý nút bấm
    check = await check_user_joined_contact_bot(context.bot, user_id)
    
    if all(check.values()):
        # Xử lý các nút bấm
        if text == "💰 Số dư của tôi": 
            balance = user_data["balance"] 
            await update.message.reply_text(f"💸 Số dư hiện tại của bạn là: **{balance} VNĐ**", parse_mode='Markdown')
            
        elif text == "🎁 Rút code": 
            await update.message.reply_text(
                "📝 **HƯỚNG DẪN RÚT CODE:**\n\n"
                f"Sử dụng lệnh: `/rutcode [TNV TRONG CPBANK] [SỐ TIỀN]`\n"
                f"Ví dụ: `/rutcode admincpbank 10000`\n"
                f"Số tiền rút nhỏ nhất là: **{MIN_CODE_VALUE} VNĐ**.\n",
                parse_mode='Markdown'
            )
        
        elif text == "💎 Mời bạn bè": 
            invite_link_base = data_load.get("invite_link")
            
            if not invite_link_base:
                 await update.message.reply_text("Lỗi cấu hình: Không tìm thấy link mời trong data.json.")
                 return

            user_id = update.effective_user.id
            personal_invite_link = f"{invite_link_base}?start=ref{user_id}" 
            
            message_text = (
                f"💎 **LINK MỜI BẠN BÈ CỦA BẠN** 💎\n\n"
                f"Sử dụng link này để mời bạn bè tham gia bot:\n"
                f"**`{personal_invite_link}`**\n\n"
                f"MỜI 1 BẠN XÁC THỰC THÀNH CÔNG = {REWARD_AMOUNT} VNĐ!\n\n"
                f"ĐIỂM TỐI THIỂU RÚT LÀ {MIN_WITHDRAWAL_AMOUNT} VNĐ "
            )
            
            await update.message.reply_text(
                message_text, 
                parse_mode='Markdown',
                disable_web_page_preview=True 
            )

        elif text == "🎮 Link Game": 
            game_link = data_load.get("game_link", "Đang cập nhật.")
            await update.message.reply_text(f"🎁 Link Game: **{game_link}**", parse_mode='Markdown')

        elif text == "☎️ CSKH Hỗ Trợ": 
            support_user = data_load.get("support", "Liên hệ admin.")
            await update.message.reply_text(f"📞 Liên hệ hỗ trợ tại: {support_user}")
            
        else: 
            await update.message.reply_text("🤖 Vui lòng sử dụng các nút bên dưới hoặc lệnh **/rutcode**.", reply_markup=main_keyboard)
                
    else:
        # Nếu chưa là thành viên, gửi lại thông báo yêu cầu start
        msg = "⛔️ Bạn chưa đủ điều kiện. Vui lòng nhấn **/start** để xem hướng dẫn tham gia nhóm."
        await update.message.reply_text(msg, reply_markup=main_keyboard)
        return

# HÀM CHÍNH
def main() -> None:
    # Khởi tạo Application
    application = ApplicationBuilder().token(TOKEN).build()

    # Thêm các Handler
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("rutcode", rutcode_command)) 
    
    # ĐĂNG KÝ LỆNH ADMIN (Chỉ hoạt động với ADMIN_ID)
    application.add_handler(CommandHandler("admin_add", admin_add_balance_command)) 
    application.add_handler(CommandHandler("admin_check", admin_check_command)) # <-- LỆNH MỚI
    
    # MessageHandler xử lý tất cả tin nhắn văn bản (kể cả nút bấm)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buttons))

    # Bắt đầu bot
    print("Bot đang chạy...")
    application.run_polling()

if __name__ == '__main__':
    main()