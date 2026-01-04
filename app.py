import sys
from flask import Flask, render_template, url_for, flash, redirect, request, session, jsonify, send_file
from forms import RegistrationForm, LoginForm
from logic import CashierSystem, Inventory
from datetime import datetime, timedelta    
import json
import os
import base64
from werkzeug.utils import secure_filename
from io import BytesIO
import logging

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# ============================================
# CHECK DEPENDENCIES
# ============================================

# Coba import PIL, jika tidak ada, disable fitur
try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    print("INFO: Pillow not installed. Profile picture features will be limited.")

# Cek apakah barcode library tersedia
try:
    import barcode
    from barcode.writer import ImageWriter
    BARCODE_AVAILABLE = True
except ImportError:
    BARCODE_AVAILABLE = False
    print("INFO: Python-barcode not installed. Barcode generation features will be limited.")

# ============================================
# APP CONFIGURATION
# ============================================

app = Flask(__name__)
app.config['SECRET_KEY'] = 'justcani-secret-key-2025'

# Upload configuration
UPLOAD_FOLDER = 'static/uploads/profile_pics'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def create_upload_folder():
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

def process_and_save_image(file, user_id):
    if not PILLOW_AVAILABLE:
        # Fallback sederhana
        filename = f"profile_{user_id}.jpg"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        file.save(filepath)
        return f"/{UPLOAD_FOLDER}/{filename}"
    
    try:
        img = Image.open(file)
        
        if img.mode in ('RGBA', 'LA'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            if img.mode == 'RGBA':
                background.paste(img, mask=img.split()[3])
            else:
                background.paste(img, mask=img.split()[1])
            img = background
        
        width, height = img.size
        min_dim = min(width, height)
        left = (width - min_dim) / 2
        top = (height - min_dim) / 2
        right = (width + min_dim) / 2
        bottom = (height + min_dim) / 2
        img = img.crop((left, top, right, bottom))
        
        img = img.resize((400, 400), Image.Resampling.LANCZOS)
        
        filename = f"profile_{user_id}.jpg"
        filepath = os.path.join(UPLOAD_FOLDER, filename)
        img.save(filepath, 'JPEG', quality=85)
        
        return f"/{UPLOAD_FOLDER}/{filename}"
        
    except Exception as e:
        print(f"Error processing image: {e}")
        return None

@app.route('/')
def home():
    return "Website sudah jalan di Vercel!"

#=============================================
# UTILITY FUNCTIONS
# ============================================

def get_time_ago(timestamp):
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    
    now = datetime.now()
    diff = now - timestamp
    
    if diff.days > 0:
        return f"{diff.days} hari lalu"
    elif diff.seconds > 3600:
        hours = diff.seconds // 3600
        return f"{hours} jam lalu"
    elif diff.seconds > 60:
        minutes = diff.seconds // 60
        return f"{minutes} menit lalu"
    else:
        return "Baru saja"

# ============================================
# ROUTES - AUTHENTICATION & PROFILE
# ============================================

@app.route("/")
@app.route("/home")
def home():
    return render_template('home.html', title='Home')

@app.route("/register", methods=['GET', 'POST'])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        sys = CashierSystem()
        berhasil = sys.register_user(
            form.username.data, 
            form.email.data, 
            form.whatsapp.data, 
            form.password.data
        )
        sys.close()
        if berhasil:
            flash('Akun berhasil dibuat! Silakan login.', 'success')
            return redirect(url_for('login'))
        flash('Gagal daftar. Email/Username mungkin sudah ada.', 'danger')
    return render_template('register.html', title='Daftar', form=form)

@app.route("/login", methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        sys = CashierSystem()
        user = sys.login_user(form.email.data, form.password.data)
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['email'] = user['email']
            session['role'] = user['role']
            session['profile_pic'] = user.get('profile_pic', '/static/img/default-avatar.png')
            
            flash(f'Selamat datang, {user["username"]}!', 'success')
            
            if user['role'] == 'admin':
                return redirect(url_for('admin'))
            else:
                return redirect(url_for('kasir'))
        flash('Login gagal. Cek email/username dan password.', 'danger')
    return render_template('login.html', title='Masuk', form=form)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('home'))

@app.route("/api/upload_profile_pic", methods=['POST'])
def upload_profile_pic():
    if not session.get('user_id'):
        return jsonify({"success": False, "message": "Silakan login"})
    
    if 'photo' not in request.files:
        return jsonify({"success": False, "message": "Tidak ada file"})
    
    file = request.files['photo']
    
    if file.filename == '':
        return jsonify({"success": False, "message": "Nama file kosong"})
    
    if not allowed_file(file.filename):
        return jsonify({"success": False, "message": "Format tidak didukung"})
    
    create_upload_folder()
    
    try:
        profile_pic_url = process_and_save_image(file, session['user_id'])
        
        if not profile_pic_url:
            return jsonify({"success": False, "message": "Gagal memproses"})
        
        # Update database
        sys = CashierSystem()
        cursor = sys.db.cursor()
        sql = "UPDATE users SET profile_pic = %s WHERE id = %s"
        cursor.execute(sql, (profile_pic_url, session['user_id']))
        sys.db.commit()
        sys.close()
        
        session['profile_pic'] = profile_pic_url
        
        return jsonify({
            "success": True, 
            "message": "Foto berhasil diupdate",
            "profile_pic": profile_pic_url
        })
        
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

# ============================================
# ROUTES - MAIN PAGES
# ============================================

@app.route("/kasir")
def kasir():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    return render_template('kasir.html', title='Menu Kasir')

@app.route("/admin")
def admin():
    if session.get('role') != 'admin':
        flash('Akses ditolak! Anda bukan admin.', 'danger')
        return redirect(url_for('home'))
    return render_template('admin.html', title='Admin Dashboard')

@app.route("/products")
def products():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    return render_template('products.html', title='Daftar Produk')


# ============================================
# log request details for debugging headers and body
# ============================================

@app.before_request
def log_request_info():
    logger.debug('Headers: %s', request.headers)
    logger.debug('Body: %s', request.get_data())

@app.route("/api/debug_db")
def debug_db():
    """Simple debug endpoint"""
    try:
        import mysql.connector
        conn = mysql.connector.connect(
            host='localhost',
            user='root',
            password='',
            database='db_kasir1'
        )
        cursor = conn.cursor(dictionary=True)
        
        # Cek produk biasa
        cursor.execute("SELECT COUNT(*) as count FROM produk_biasa")
        biasa_count = cursor.fetchone()
        
        # Cek produk lelang
        cursor.execute("SELECT COUNT(*) as count FROM produk_lelang")
        lelang_count = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        return f"""
        <h3>Database Status</h3>
        <p>Produk Biasa: {biasa_count['count']} item</p>
        <p>Produk Lelang: {lelang_count['count']} item</p>
        <p>✅ Database OK</p>
        """
    except Exception as e:
        return f"<h3>❌ ERROR</h3><p>{str(e)}</p>"

# ============================================
# ROUTES - ADMIN FEATURES
# ============================================

@app.route("/admin/dashboard")
def admin_dashboard():
    if session.get('role') != 'admin':
        flash('Akses ditolak! Hanya admin.', 'danger')
        return redirect(url_for('home'))
    return render_template('admin_dashboard.html', title='Dashboard Statistik')

@app.route("/admin/history")
def admin_history():
    if session.get('role') != 'admin':
        flash('Akses ditolak! Hanya admin.', 'danger')
        return redirect(url_for('home'))
    
    date_filter = request.args.get('date', '')
    
    sys = CashierSystem()
    
    if date_filter:
        transactions = sys.transaction.history.get_transactions_by_date(date_filter, date_filter)
    else:
        transactions = sys.transaction.history.get_all_transactions(limit=100)
    
    today = datetime.now().strftime("%Y-%m-%d")
    daily_summary = sys.transaction.history.get_daily_summary(today)
    
    sys.close()
    
    return render_template('admin_history.html', 
                         title='History Transaksi',
                         transactions=transactions,
                         daily_summary=daily_summary,
                         date_filter=date_filter)

@app.route("/admin/add", methods=['POST'])
def admin_add():
    if session.get('role') != 'admin':
        return redirect(url_for('home'))
    
    sys = CashierSystem()
    sku = request.form.get('sku')
    name = request.form.get('name')
    harga = request.form.get('harga')
    expired_date = request.form.get('expired_date')
    
    # Auto-generate barcode jika tersedia
    if BARCODE_AVAILABLE and sku:
        try:
            # Generate barcode
            code128 = barcode.get_barcode_class('code128')
            barcode_instance = code128(str(sku), writer=ImageWriter())
            
            # Save to bytes
            buffer = BytesIO()
            barcode_instance.write(buffer)
            buffer.seek(0)
            
            # Convert to base64
            barcode_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            barcode_data = f"data:image/png;base64,{barcode_base64}"
            
            # Save to database
            sys.inventory.save_barcode_to_db(sku, barcode_data)
            print(f"✅ Barcode auto-generated for SKU: {sku}")
            
        except Exception as e:
            print(f"⚠️ Barcode generation failed: {e}")
    
    sys.inventory.add_produk_baru(sku, name, harga, expired_date)
    sys.close()
    
    flash('Produk berhasil ditambahkan!', 'success')
    return redirect(url_for('admin'))

@app.route("/admin/restock", methods=['POST'])
def admin_restock():
    if session.get('role') != 'admin':
        return redirect(url_for('home'))
    
    sys = CashierSystem()
    cursor = sys.db.cursor()
    sql = "UPDATE produk_biasa SET stok = stok + %s WHERE no_SKU = %s"
    cursor.execute(sql, (request.form.get('qty'), request.form.get('sku')))
    sys.db.commit()
    sys.close()
    flash('Stok berhasil diperbarui!', 'success')
    return redirect(url_for('admin'))

@app.route("/admin/move_lelang", methods=['POST'])
def admin_move_lelang():
    if session.get('role') != 'admin':
        flash('Akses ditolak! Hanya admin yang bisa pindah ke lelang.', 'danger')
        return redirect(url_for('admin'))
    
    sku = request.form.get('sku')
    reason = request.form.get('reason')
    
    if not sku or not reason:
        flash('SKU dan alasan harus diisi!', 'danger')
        return redirect(url_for('admin'))
    
    sys = CashierSystem()
    success, message = sys.inventory.move_to_lelang(sku, reason)
    sys.close()
    
    flash(message, 'success' if success else 'danger')
    return redirect(url_for('admin'))

# ============================================
# API ENDPOINTS - PRODUCTS & TRANSACTIONS
# ============================================

@app.route("/api/search")
def api_search():
    """API untuk search produk biasa"""
    try:
        query = request.args.get('q', '')
        print(f"[DEBUG] Searching produk biasa: '{query}'")
        
        sys = CashierSystem()
        if not sys.db:
            print("[ERROR] Database not connected")
            return jsonify([]), 200
        
        results = sys.inventory.search_produk(query)
        print(f"[DEBUG] Found {len(results)} results")
        
        sys.close()
        return jsonify(results)
        
    except Exception as e:
        print(f"[ERROR] api_search failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/search_lelang")
def api_search_lelang():
    """API untuk search produk lelang"""
    try:
        query = request.args.get('q', '')
        print(f"[DEBUG] Searching produk lelang: '{query}'")
        
        sys = CashierSystem()
        if not sys.db:
            print("[ERROR] Database not connected")
            return jsonify([]), 200
        
        results = sys.inventory.search_produk_lelang(query)
        print(f"[DEBUG] Found {len(results)} results")
        
        sys.close()
        return jsonify(results)
        
    except Exception as e:
        print(f"[ERROR] api_search_lelang failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/checkout", methods=['POST'])
def api_checkout():
    if not session.get('user_id'):
        return jsonify({"success": False, "message": "Silakan login terlebih dahulu"})
    
    data = request.json
    sys = CashierSystem()
    success, msg = sys.transaction.checkout(
        data['items'],
        session['user_id'],
        session['username']
    )
    sys.close()
    return jsonify({"success": success, "message": msg})

@app.route("/api/checkout_lelang", methods=['POST'])
def api_checkout_lelang():
    if not session.get('user_id'):
        return jsonify({"success": False, "message": "Silakan login terlebih dahulu"})
    
    data = request.json
    sys = CashierSystem()
    success, msg = sys.transaction.checkout_lelang(
        data['items'],
        session['user_id'],
        session['username']
    )
    sys.close()
    return jsonify({"success": success, "message": msg})

@app.route("/api/transaction/<int:transaction_id>")
def api_transaction_detail(transaction_id):
    if session.get('role') != 'admin':
        return jsonify({"error": "Unauthorized"}), 401
    
    sys = CashierSystem()
    cursor = sys.db.cursor(dictionary=True)
    try:
        sql = "SELECT * FROM transaction_history WHERE id = %s"
        cursor.execute(sql, (transaction_id,))
        transaction = cursor.fetchone()
        
        if not transaction:
            return jsonify({"error": "Transaction not found"}), 404
        
        return jsonify(transaction)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        sys.close()

# ============================================
# API ENDPOINTS - STATISTICS & REPORTS
# ============================================

@app.route("/api/stats")
def api_stats():
    if session.get('role') != 'admin':
        return jsonify({"error": "Unauthorized"}), 401
    
    period = request.args.get('period', 'today')
    end_date = datetime.now()
    
    if period == 'today':
        start_date = end_date.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == 'week':
        start_date = end_date - timedelta(days=7)
    elif period == 'month':
        start_date = end_date - timedelta(days=30)
    else:
        start_date = end_date.replace(hour=0, minute=0, second=0, microsecond=0)
    
    sys = CashierSystem()
    
    try:
        cursor = sys.db.cursor(dictionary=True)
        start_str = start_date.strftime('%Y-%m-%d %H:%M:%S')
        end_str = end_date.strftime('%Y-%m-%d %H:%M:%S')
        
        sql = """
        SELECT * FROM transaction_history 
        WHERE transaction_date BETWEEN %s AND %s
        ORDER BY transaction_date DESC
        """
        cursor.execute(sql, (start_str, end_str))
        transactions = cursor.fetchall()
        
        total_revenue = sum(t['total_amount'] for t in transactions)
        total_transactions = len(transactions)
        avg_transaction = total_revenue / total_transactions if total_transactions > 0 else 0
        
        total_products = 0
        for t in transactions:
            try:
                details = json.loads(t['details'])
                total_products += sum(item.get('qty', 0) for item in details)
            except:
                pass
        
        sales_by_day = {}
        for t in transactions:
            date_key = t['transaction_date'].strftime('%d/%m') if isinstance(t['transaction_date'], datetime) else t['transaction_date'][:10]
            sales_by_day[date_key] = sales_by_day.get(date_key, 0) + t['total_amount']
        
        transaction_types = {'biasa': 0, 'lelang': 0}
        for t in transactions:
            transaction_types[t['transaction_type']] += 1
        
        product_sales = {}
        for t in transactions:
            try:
                details = json.loads(t['details'])
                for item in details:
                    product_key = item.get('name', f"SKU:{item.get('sku')}")
                    if product_key not in product_sales:
                        product_sales[product_key] = {'sold': 0, 'revenue': 0}
                    product_sales[product_key]['sold'] += item.get('qty', 0)
                    product_sales[product_key]['revenue'] += item.get('subtotal', 0)
            except:
                pass
        
        top_products = sorted(
            [{'name': k, 'sold': v['sold'], 'revenue': v['revenue']} 
             for k, v in product_sales.items()],
            key=lambda x: x['sold'],
            reverse=True
        )[:5]
        
        recent_transactions = []
        for t in transactions[:10]:
            time_ago = get_time_ago(t['transaction_date'])
            recent_transactions.append({
                'transaction_id': t['transaction_id'],
                'username': t['username'],
                'total_amount': t['total_amount'],
                'time_ago': time_ago
            })
        
        stats = {
            'summary': {
                'total_revenue': float(total_revenue),
                'total_transactions': total_transactions,
                'avg_transaction': float(avg_transaction),
                'total_products_sold': total_products
            },
            'charts': {
                'sales_trend': {
                    'labels': list(sales_by_day.keys()),
                    'data': list(sales_by_day.values())
                },
                'transaction_types': {
                    'labels': ['Biasa', 'Lelang'],
                    'data': [transaction_types['biasa'], transaction_types['lelang']]
                }
            },
            'tables': {
                'top_products': top_products,
                'recent_transactions': recent_transactions
            }
        }
        
        return jsonify(stats)
        
    except Exception as e:
        print(f"Error getting stats: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        sys.close()

# ============================================
# API ENDPOINTS - BARCODE MANAGEMENT
# ============================================

@app.route("/api/products/for_barcode")
def api_products_for_barcode():
    """Get all products for barcode dropdown - FIXED"""
    if not session.get('user_id'):
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        import mysql.connector
        conn = mysql.connector.connect(
            host='localhost',
            user='root',
            password='',
            database='db_kasir1'
        )
        sys = CashierSystem()
        cursor = conn.cursor(dictionary=True)
        
        # Get ALL products (biasa + lelang)
        products = []
        
        # Get regular products
        cursor.execute("""
            SELECT 
                no_SKU as sku, 
                Name_product as name, 
                Price as price,
                'biasa' as type,
                CASE 
                    WHEN barcode_image IS NOT NULL AND barcode_image != '' THEN 1
                    ELSE 0 
                END as has_barcode
            FROM produk_biasa 
            ORDER BY Name_product
        """)
        regular = cursor.fetchall()
        products.extend(regular)
        
        # Get auction products
        cursor.execute("""
            SELECT 
                no_SKU as sku, 
                Name_product as name, 
                Price as price,
                'lelang' as type,
                CASE 
                    WHEN barcode_image IS NOT NULL AND barcode_image != '' THEN 1
                    ELSE 0 
                END as has_barcode
            FROM produk_lelang 
            ORDER BY Name_product
        """)
        auction = cursor.fetchall()
        products.extend(auction)
        
        cursor.close()
        conn.close()
        
        print(f"[DEBUG] Found {len(products)} products for barcode dropdown")
        
        return jsonify({
            "success": True,
            "products": products,
            "count": len(products)
        })
        
    except Exception as e:
        print(f"[ERROR] api_products_for_barcode: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        sys.close()

@app.route("/api/barcode/<sku>/image")
def get_barcode_image(sku):
    """Get existing barcode image"""
    sys = CashierSystem()
    cursor = sys.db.cursor(dictionary=True)
    
    try:
        # Check in produk_biasa
        cursor.execute("""
            SELECT barcode_image 
            FROM produk_biasa 
            WHERE no_SKU = %s AND barcode_image IS NOT NULL
        """, (sku,))
        result = cursor.fetchone()
        
        if not result:
            # Check in produk_lelang
            cursor.execute("""
                SELECT barcode_image 
                FROM produk_lelang 
                WHERE no_SKU = %s AND barcode_image IS NOT NULL
            """, (sku,))
            result = cursor.fetchone()
        
        if result and result['barcode_image']:
            return jsonify({
                "success": True,
                "barcode": result['barcode_image']
            })
        
        return jsonify({"success": False, "message": "Barcode tidak ditemukan"})
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        sys.close()

@app.route("/api/barcode/generate_all", methods=['POST'])
def generate_all_barcodes():
    """Generate barcode untuk semua produk yang belum punya"""
    if session.get('role') != 'admin':
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        import mysql.connector
        conn = mysql.connector.connect(
            host='localhost',
            user='root',
            password='',
            database='db_kasir1'
        )
        generate_barcode_for_product = sys.generate_barcode_for_product  # Reuse existing function
        cursor = conn.cursor(dictionary=True)
        
        # Cari produk tanpa barcode
        cursor.execute("""
            SELECT no_SKU, Name_product, Price 
            FROM produk_biasa 
            WHERE barcode_image IS NULL OR barcode_image = ''
        """)
        biasa = cursor.fetchall()
        
        cursor.execute("""
            SELECT no_SKU, Name_product, Price 
            FROM produk_lelang 
            WHERE barcode_image IS NULL OR barcode_image = ''
        """)
        lelang = cursor.fetchall()
        
        all_products = biasa + lelang
        generated = 0
        
        # Generate barcode untuk setiap produk
        for product in all_products:
            try:
                # Panggil fungsi generate barcode
                barcode_data = generate_barcode_for_product(product['no_SKU'])
                if barcode_data:
                    generated += 1
            except:
                continue
        
        cursor.close()
        conn.close()
        
        return jsonify({
            "success": True,
            "message": f"Generated {generated} barcodes from {len(all_products)} products",
            "total": len(all_products),
            "generated": generated
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/barcode/status")
def api_barcode_status():
    """Get barcode generation status"""
    if not session.get('user_id'):
        return jsonify({"error": "Unauthorized"}), 401
    
    sys = CashierSystem()
    cursor = sys.db.cursor(dictionary=True)
    
    try:
        # Count total products
        cursor.execute("SELECT COUNT(*) as total FROM produk_biasa")
        regular_total = cursor.fetchone()['total']
        
        cursor.execute("SELECT COUNT(*) as total FROM produk_lelang")
        auction_total = cursor.fetchone()['total']
        total_products = regular_total + auction_total
        
        # Count with barcode
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM produk_biasa 
            WHERE barcode_image IS NOT NULL AND barcode_image != ''
        """)
        regular_with = cursor.fetchone()['count']
        
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM produk_lelang 
            WHERE barcode_image IS NOT NULL AND barcode_image != ''
        """)
        auction_with = cursor.fetchone()['count']
        total_with = regular_with + auction_with
        
        # Calculate progress
        progress = round((total_with / total_products * 100), 2) if total_products > 0 else 0
        
        return jsonify({
            "success": True,
            "status": {
                "total_products": total_products,
                "with_barcode": total_with,
                "without_barcode": total_products - total_with,
                "progress_percentage": progress
            }
        })
        
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        sys.close()

@app.route("/admin/history/monthly")
def admin_monthly_report():
    if session.get('role') != 'admin':
        return jsonify({"error": "Unauthorized"}), 401
    
    year = request.args.get('year', datetime.now().year)
    month = request.args.get('month', datetime.now().month)
    
    sys = CashierSystem()
    report = sys.transaction.history.get_monthly_report(year, month)
    sys.close()
    
    return jsonify(report)

# ============================================
# API ENDPOINTS - BARCODE FEATURES
# ============================================

@app.route("/api/barcode/<sku>")
def generate_barcode(sku):
    """Generate barcode image untuk produk"""
    try:
        sys = CashierSystem()
        cursor = sys.db.cursor(dictionary=True)
        
        # Cek apakah produk ada
        cursor.execute("SELECT no_SKU, Name_product, Price FROM produk_biasa WHERE no_SKU = %s", (sku,))
        product = cursor.fetchone()
        
        if not product:
            # Cek di produk lelang
            cursor.execute("SELECT no_SKU, Name_product, Price FROM produk_lelang WHERE no_SKU = %s", (sku,))
            product = cursor.fetchone()
        
        if not product:
            cursor.close()
            sys.close()
            return jsonify({
                "success": False,
                "message": f"Produk dengan SKU {sku} tidak ditemukan"
            }), 404
        
        # Cek apakah barcode sudah ada di database
        try:
            cursor.execute("SELECT barcode_image FROM produk_biasa WHERE no_SKU = %s AND barcode_image IS NOT NULL", (sku,))
            result = cursor.fetchone()
            
            if result and result['barcode_image']:
                # Barcode sudah ada di database
                cursor.close()
                sys.close()
                return jsonify({
                    "success": True,
                    "sku": sku,
                    "barcode": result['barcode_image'],
                    "cached": True,
                    "product": product
                })
        except:
            pass  # Kolom mungkin belum ada
        
        # Generate barcode baru
        if not BARCODE_AVAILABLE:
            cursor.close()
            sys.close()
            return jsonify({
                "success": False,
                "message": "Library barcode tidak terinstall. Install: pip install python-barcode"
            }), 500
        
        # Gunakan Code128 format
        code128 = barcode.get_barcode_class('code128')
        barcode_instance = code128(str(sku), writer=ImageWriter())
        
        # Save ke bytes
        buffer = BytesIO()
        barcode_instance.write(buffer)
        buffer.seek(0)
        
        # Convert ke base64
        barcode_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
        barcode_data = f"data:image/png;base64,{barcode_base64}"
        
        # Simpan ke database
        try:
            # Coba update produk biasa
            cursor.execute("""
                UPDATE produk_biasa 
                SET barcode_image = %s 
                WHERE no_SKU = %s
            """, (barcode_data, sku))
            
            # Coba update produk lelang
            cursor.execute("""
                UPDATE produk_lelang 
                SET barcode_image = %s 
                WHERE no_SKU = %s
            """, (barcode_data, sku))
            
            sys.db.commit()
        except Exception as e:
            print(f"Warning: Could not save barcode to database: {e}")
            # Lanjutkan saja, mungkin kolom belum ada
        
        cursor.close()
        sys.close()
        
        return jsonify({
            "success": True,
            "sku": sku,
            "barcode": barcode_data,
            "cached": False,
            "product": product
        })
        
    except Exception as e:
        print(f"Error generating barcode: {e}")
        return jsonify({
            "success": False,
            "message": f"Error: {str(e)}"
        }), 500

@app.route("/api/barcode/<sku>/download")
def download_barcode(sku):
    """Download barcode as PNG file"""
    try:
        if not BARCODE_AVAILABLE:
            return jsonify({
                "success": False,
                "message": "Library barcode tidak terinstall"
            }), 500
        
        # Generate barcode
        code128 = barcode.get_barcode_class('code128')
        barcode_instance = code128(str(sku), writer=ImageWriter())
        
        # Save to bytes
        buffer = BytesIO()
        barcode_instance.write(buffer)
        buffer.seek(0)
        
        # Return as downloadable file
        return send_file(
            buffer,
            mimetype='image/png',
            as_attachment=True,
            download_name=f'barcode_{sku}.png'
        )
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/barcode/status/<sku>")
def check_barcode_status(sku):
    """Cek status barcode produk"""
    if not session.get('user_id'):
        return jsonify({"error": "Unauthorized"}), 401
    
    sys = CashierSystem()
    cursor = sys.db.cursor(dictionary=True)
    
    try:
        # Cek di produk biasa
        cursor.execute("""
            SELECT no_SKU, Name_product, barcode_image 
            FROM produk_biasa 
            WHERE no_SKU = %s
        """, (sku,))
        
        result = cursor.fetchone()
        
        if not result:
            # Cek di produk lelang
            cursor.execute("""
                SELECT no_SKU, Name_product, barcode_image 
                FROM produk_lelang 
                WHERE no_SKU = %s
            """, (sku,))
            result = cursor.fetchone()
        
        if not result:
            return jsonify({
                "success": False,
                "message": "Produk tidak ditemukan"
            }), 404
        
        has_barcode = result['barcode_image'] is not None and result['barcode_image'] != ''
        
        return jsonify({
            "success": True,
            "sku": sku,
            "product_name": result['Name_product'],
            "has_barcode": has_barcode,
            "message": "Produk sudah memiliki barcode" if has_barcode else "Produk belum memiliki barcode"
        })
            
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
    finally:
        cursor.close()
        sys.close()

@app.route("/api/products/without_barcode")
def api_products_without_barcode():
    """Get all products without barcode"""
    if session.get('role') != 'admin':
        return jsonify({"error": "Unauthorized"}), 401
    
    sys = CashierSystem()
    cursor = sys.db.cursor(dictionary=True)
    
    try:
        # Get products without barcode from produk_biasa
        cursor.execute("""
            SELECT no_SKU, Name_product, Price, stok 
            FROM produk_biasa 
            WHERE barcode_image IS NULL OR barcode_image = ''
        """)
        regular = cursor.fetchall()
        
        # Get products without barcode from produk_lelang
        cursor.execute("""
            SELECT no_SKU, Name_product, Price 
            FROM produk_lelang 
            WHERE barcode_image IS NULL OR barcode_image = ''
        """)
        auction = cursor.fetchall()
        
        products = []
        for p in regular:
            products.append({
                'no_SKU': p['no_SKU'],
                'Name_product': p['Name_product'],
                'Price': p['Price'],
                'type': 'biasa',
                'stok': p['stok']
            })
        
        for p in auction:
            products.append({
                'no_SKU': p['no_SKU'],
                'Name_product': p['Name_product'],
                'Price': p['Price'],
                'type': 'lelang',
                'stok': None
            })
        
        return jsonify(products)
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        sys.close()

@app.route("/api/print_barcode/<sku>")
def print_barcode_label(sku):
    """Generate printable barcode label"""
    if session.get('role') != 'admin':
        return jsonify({"error": "Unauthorized"}), 401
    
    sys = CashierSystem()
    cursor = sys.db.cursor(dictionary=True)
    
    try:
        # Ambil data produk
        cursor.execute("SELECT Name_product, Price FROM produk_biasa WHERE no_SKU = %s", (sku,))
        product = cursor.fetchone()
        
        if not product:
            cursor.execute("SELECT Name_product, Price FROM produk_lelang WHERE no_SKU = %s", (sku,))
            product = cursor.fetchone()
        
        if not product:
            return jsonify({"error": "Produk tidak ditemukan"}), 404
        
        # Generate barcode URL
        barcode_url = f"https://barcode.tec-it.com/barcode.ashx?data={sku}&code=Code128&dpi=96"
        
        # HTML untuk label barcode
        html_label = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Barcode Label - {sku}</title>
            <style>
                @media print {{
                    body {{ margin: 0; padding: 0; }}
                    .label {{ page-break-inside: avoid; }}
                }}
                body {{ font-family: Arial, sans-serif; padding: 10px; }}
                .label {{ 
                    width: 3in; 
                    height: 1.5in; 
                    border: 1px solid #000; 
                    padding: 8px;
                    margin: 5px;
                    display: inline-block;
                    vertical-align: top;
                    box-sizing: border-box;
                }}
                .product-name {{ 
                    font-size: 12px; 
                    font-weight: bold; 
                    margin-bottom: 3px;
                    height: 30px;
                    overflow: hidden;
                }}
                .sku {{ 
                    font-size: 10px; 
                    color: #666;
                    margin-bottom: 3px;
                }}
                .price {{ 
                    font-size: 14px; 
                    font-weight: bold; 
                    color: #d00;
                    margin-bottom: 5px;
                }}
                .barcode {{ 
                    margin: 3px 0;
                    text-align: center;
                }}
                .print-info {{
                    font-size: 8px; 
                    text-align: center;
                    color: #666;
                    margin-top: 3px;
                }}
            </style>
        </head>
        <body>
            <div class="label">
                <div class="product-name">{product['Name_product'][:25]}</div>
                <div class="sku">SKU: {sku}</div>
                <div class="price">Rp{int(product['Price']):,}</div>
                <div class="barcode">
                    <img src="{barcode_url}" 
                         alt="Barcode {sku}" 
                         width="180" 
                         height="40">
                </div>
                <div class="print-info">JustCani POS System</div>
            </div>
        </body>
        </html>
        """
        
        return html_label
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        sys.close()

# ============================================
# ERROR HANDLERS
# ============================================

@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template('500.html'), 500

# ============================================
# MAIN ENTRY POINT
# ============================================

if __name__ == '__main__':
    # Create necessary directories
    create_upload_folder()
    
    # Create static/img directory if not exists
    img_dir = 'static/img'
    if not os.path.exists(img_dir):
        os.makedirs(img_dir)
    
    print("=" * 50)
    print("🚀 JustCani POS System Starting...")
    print(f"📦 Barcode Support: {'✅ Enabled' if BARCODE_AVAILABLE else '⚠️ Not Available'}")
    print(f"🖼️  Image Support: {'✅ Enabled' if PILLOW_AVAILABLE else '⚠️ Not Available'}")
    print("=" * 50)
    
    app.run(debug=True, host='0.0.0.0', port=5000)

