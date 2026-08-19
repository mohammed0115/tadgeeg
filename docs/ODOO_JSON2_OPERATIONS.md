# تشغيل موصل Odoo JSON-2

يعتمد موصل Tadgeeg على واجهة Odoo **JSON-2** الحديثة عند المسار:

```text
POST https://<odoo-host>/json/2/<model>/<method>
Authorization: bearer <odoo-api-key>
X-Odoo-Database: <database-name>  # عند الحاجة
```

لا تستخدم الشحنة XML-RPC أو JSON-RPC القديمة؛ وثائق Odoo 19 تشير إلى أن تلك الواجهات مقررة للإزالة في Odoo 22، بينما JSON-2 هي البديل المعتمد.

## متطلبات بيئة التشغيل

لا تضع قيماً في Git. خزّن القيم في بيئة خادم Tadgeeg أو في `ERPConnection.credentials` المشفر عبر واجهة الإدارة:

```dotenv
# مثال أسماء فقط، بلا أسرار
ODOO_BASE_URL=
ODOO_DATABASE=
ODOO_API_KEY=
```

يلزم أن تكون اشتراكات Odoo من نوع يتيح External API؛ لا تتاح الواجهة الخارجية في خطط One App Free أو Standard وفق توثيق Odoo. أنشئ bot user مخصصاً بصلاحيات القراءة/الكتابة الدنيا المطلوبة لموديلات `account.move` و`purchase.order` و`res.partner`، واستخدم API key قصير العمر مع تدوير منتظم.

## تحقق قبل التفعيل

1. أنشئ `ERPConnection` من النوع `odoo` في بيئة Sandbox أولاً.
2. خزّن API key في حقل الاعتمادات المشفر، ولا تطبعه في السجلات أو الواجهة.
3. نفذ مزامنة قراءة محدودة بموديل واحد، ثم راجع `SyncRun` و`SyncRecord` وreconciliation.
4. لا فعّل بيئة Production قبل التحقق من صلاحيات bot user والاستيراد المتكرر وعدم تكرار الفواتير.

## المصدر

- [Odoo 19 External JSON-2 API](https://www.odoo.com/documentation/19.0/developer/reference/external_api.html)
- [Odoo 19 External RPC API migration notice](https://www.odoo.com/documentation/19.0/developer/reference/external_rpc_api.html)
