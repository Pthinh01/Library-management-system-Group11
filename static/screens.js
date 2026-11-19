'use strict';
// Screens follow the twenty supplied Figma references. Data always comes from Python.
const routeLink = (text, route, primary=false) => `<a class="button ${primary?'':'secondary'}" href="#${esc(route)}">${esc(text)}</a>`;
const uiButton = (text, action, id='', primary=false) => `<button type="button" class="${primary?'':'secondary'}" data-ui="${action}" data-id="${esc(id)}">${esc(text)}</button>`;
const facts = rows => `<dl class="facts">${rows.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${v}</dd>`).join('')}</dl>`;
const card = (title, body) => `<section class="card">${title?`<h2>${esc(title)}</h2>`:''}${body}</section>`;
const msg = (title, body='', kind='good') => `<section class="notice ${kind}"><strong>${esc(title)}</strong>${body}</section>`;
const day = value => value ? new Date(value).toLocaleDateString('vi-VN') : '—';
const code = (prefix, id) => `${prefix}-${String(id).padStart(4,'0')}`;
const overdue = r => r.status==='OPEN' && new Date(r.due_date)<new Date();
const lateDays = value => Math.max(0,Math.ceil((Date.now()-new Date(value))/86400000));
let bookFilter='all', loanFilter='OPEN', accountFilter='MEMBER';
let loanSearch='', accountSearch='', selectedRenew=new Set(), draft=null, returnState=null, receipt=null, successLoanId=null;
const oldProfileView=profileEditor;
field = function(name,label,value='',type='text',required=true,extra='') {
 return `<label><span>${esc(label)}${required?' *':''}</span><input name="${esc(name)}" type="${type}" value="${esc(value)}" ${required?'required':''} ${extra}></label>`;
};
function show(title, subtitle, html){setTitle(title,subtitle);$('#content').innerHTML=html;window.scrollTo(0,0);}
function go(route){close();if(location.hash.slice(1)===route)render();else location.hash=route;}
function tabs(items,active,action){return `<div class="tabs">${items.map(([id,title])=>`<button type="button" class="${active===id?'selected':''}" aria-pressed="${active===id}" data-ui="${action}" data-id="${id}">${esc(title)}</button>`).join('')}</div>`;}
function bookTile(b, extra='', clickable=true){return `<${clickable?'button':'div'} ${clickable?`type="button" data-ui="book" data-id="${b.id}"`:''} class="book-card"><img src="/cover.png" alt="Bìa sách ${esc(b.title)}"><div><strong>${esc(b.title)}</strong><small>${esc(b.publisher||b.authors||'')}</small>${extra||`<span class="good">Còn ${b.available} bản</span>`}</div></${clickable?'button':'div'}>`;}
navigation=function(){
 const route=location.hash.slice(1).split('/')[0]||'signin';
 document.body.classList.toggle('signed-out',!me);
 let links=me?.role==='MEMBER'?[['catalog','Khám phá'],['loans','Sách mượn'],['reservations','Đặt trước'],['profile','Cá nhân']]:admin()?[['dashboard','Tổng quan'],['accounts','Tài khoản'],['settings','Quy định'],['profile','Cá nhân']]:[['dashboard','Trang chủ'],['catalog','Kho sách'],['loans','Mượn trả'],['profile','Cá nhân']];
 if(window.innerWidth>=1100 && staff())links=[['dashboard','Trang chủ'],['catalog','Kho sách'],['loans','Mượn & trả'],['members','Độc giả'],['reservations','Đặt trước'],['fines','Tiền phạt'],['reports','Báo cáo'],...(admin()?[['accounts','Tài khoản'],['settings','Quy định']]:[]),['profile','Cá nhân']];
 const active=['book','copies','new-book','edit-book'].includes(route)?'catalog':['checkout','checkout-confirm','loan','return','return-preview','pay','receipt'].includes(route)?'loans':route;
 $('#navigation').innerHTML=links.map(([id,title])=>`<a href="#${id}" class="${id===active?'active':''}" ${id===active?'aria-current="page"':''}><span class="nav-symbol" aria-hidden="true">${id===active?'●':'○'}</span>${title}</a>`).join('');
 $('#identity').innerHTML=me?`<strong>${esc(me.profile.full_name)}</strong><p class="muted">${esc(roles[me.role])}</p>`:'';
 $('#header-actions').innerHTML=me?btn('Đăng xuất','logout'):'';
};
render=async function(){
 const version=++viewVersion;navigation();let [route,arg]=location.hash.slice(1).split('/');route=route||(me?(staff()?'dashboard':'catalog'):'signin');
 if(!me&&!['signin','register','catalog','book'].includes(route)){go('signin');return;}
 $('#content').innerHTML='<p class="loading" role="status">Đang tải…</p>';
 const staffOnly=['dashboard','copies','new-book','edit-book','checkout','checkout-confirm','return','return-preview','pay','members','reports','accounts','settings'];
 try{
  if(staffOnly.includes(route)&&!staff())throw new Error('Chức năng dành cho nhân viên thư viện.');
  if(['accounts','settings'].includes(route)&&!admin())throw new Error('Chức năng dành cho quản trị viên.');
  const screens={signin:()=>auth(false),register:()=>auth(true),catalog:()=>catalogView(version),book:()=>bookDetail(Number(arg)),copies:()=>copiesView(Number(arg)), 'new-book':()=>bookForm(), 'edit-book':async()=>bookForm((await api('book?id='+arg)).book),dashboard:()=>dashboardView(version),loans:()=>loansView(version),checkout:()=>checkoutForm(),'checkout-confirm':()=>checkoutConfirm(),loan:()=>loanDetail(Number(arg)),return:()=>returnForm(arg?decodeURIComponent(arg):''),'return-preview':()=>returnPreview(),pay:()=>payForm(Number(arg)),receipt:()=>receiptView(),reservations:()=>reservationsView(version),reports:()=>reportsView(),accounts:()=>accountsView(version),profile:()=>profileView(),'profile-edit':()=>oldProfileView(),members:()=>membersView(version),fines:()=>finesView(version),settings:()=>settingsView(version),transactions:()=>transactionsView()};
  await (screens[route]||screens.catalog)();
 }catch(e){if(version!==viewVersion)return;show('Không thể mở màn hình','',notice(errorMessage(e),'bad')+routeLink('Quay lại',me?(staff()?'dashboard':'catalog'):'signin'));}
};
auth=function(register=false){
 show(register?'Tạo tài khoản':'Chào mừng trở lại',register?'Dành cho độc giả của thư viện':'LIBRARY · Mỗi cuốn sách, một hành trình',
 `${register?'':card('',`<div class="hero"><strong>Thư viện trong tầm tay</strong><p class="muted">Tra cứu, mượn và quản lý sách dễ dàng.</p><h2>Đọc nhiều hơn.<br>Khám phá xa hơn.</h2></div>`)}
 <form id="auth-form" class="stack">${register?field('full_name','Họ và tên','','text',true,'autocomplete="name" placeholder="Nguyễn Phúc Thịnh"')+field('email','Email','','email',true,'autocomplete="email"')+field('username','Tên đăng nhập','','text',true,'minlength="3" maxlength="50" autocomplete="username"'):field('identity','Email hoặc tên đăng nhập','','text',true,'autocomplete="username" placeholder="thinh.nguyen"')}${field('password','Mật khẩu','','password',true,`minlength="${register?8:1}" maxlength="256" autocomplete="${register?'new-password':'current-password'}"`)}${register?field('confirmation','Nhập lại mật khẩu','','password'):''}<p class="error" role="alert"></p>${register?'<p class="muted">Mật khẩu tối thiểu 8 ký tự. Thông tin có dấu * là bắt buộc.</p>':''}<button>${register?'Đăng ký':'Đăng nhập'}</button></form>${routeLink(register?'Đã có tài khoản? Đăng nhập':'Tạo tài khoản độc giả',register?'signin':'register')}${register?'':'<p class="muted">Bạn vẫn có thể tra cứu sách khi chưa đăng nhập.</p>'+routeLink('Khám phá thư viện','catalog')}`);
 bindForm('auth-form',async d=>{await api(register?'register':'login',d);if(register){toast('Đăng ký thành công. Bạn có thể đăng nhập.');go('signin');}else{me=await api('me');go(staff()?'dashboard':'catalog');}});
};
catalogView=async function(version){
 const data=await api('catalog?q='+encodeURIComponent(search)+'&page='+page+'&availability='+bookFilter);if(version!==viewVersion)return;cache=data.items;
 const shown=data.items;
 show(staff()?'Kho sách':'Khám phá sách',`${data.total.toLocaleString('vi-VN')} đầu sách · Quản lý theo bản sao`,
 `<form id="search-form">${field('q','Tìm tên sách, tác giả, ISBN',search,'search',false,'maxlength="200"')}<button class="visually-hidden">Tìm kiếm</button></form>${tabs([['all','Tất cả'],['available','Còn sách'],['borrowed','Đang mượn']],bookFilter,'book-filter')}<div class="screen-grid stack">${shown.map(b=>bookTile(b)).join('')||empty('Không tìm thấy sách')}</div>${staff()?routeLink('Thêm đầu sách','new-book',true):''}<div class="pagination"><small>Trang ${page} / ${Math.max(1,Math.ceil(data.total/20))}</small><div>${page>1?btn('Trước','prev-page'):''}${page*20<data.total?btn('Tiếp','next-page'):''}</div></div>${!me?routeLink('Đăng nhập','signin'):''}`);
 bindForm('search-form',async d=>{search=d.q;page=1;await render();});
};
bookDetail=async function(id){
 const {book:b,copies}=await api('book?id='+id);window.currentBook={book:b,copies};
 const available=copies.filter(c=>c.status==='AVAILABLE').length, borrowed=copies.filter(c=>c.status==='ON_LOAN').length;
 show('Chi tiết sách',`KHO SÁCH / ${code('SGK',b.id)}`,bookTile(b,`<span class="good">Còn ${available} bản</span>`,false)+
 card('Thông tin đầu sách',facts([['ISBN',esc(b.isbn)],['Thể loại',esc(b.category)],['Năm xuất bản',b.publication_year],['Tác giả',esc(b.authors)]])+`<p class="muted">${esc(b.description)}</p>`)+
 card('Bản sao vật lý',facts([['Tổng số',copies.length+' bản'],['Sẵn sàng cho mượn',`<span class="good">${available} bản</span>`],['Đang mượn',borrowed+' bản']]))+
 (staff()?routeLink('Xem bản sao & vị trí','copies/'+id)+routeLink('Chỉnh sửa đầu sách','edit-book/'+id):me&&available===0?btn('Đặt trước','reserve',id,''):notice('Liên hệ quầy thư viện để mượn bản sao sẵn sàng.')));
};
bookForm=function(b={}){
 show(b.id?'Chỉnh sửa đầu sách':'Thêm đầu sách','Thông tin chung của sách',`<form id="book-form" class="stack"><div class="form-grid">${field('title','Tên sách',b.title||'')}${field('isbn','ISBN',b.isbn||'')}${field('authors','Tác giả',b.authors||'')}${field('category','Thể loại',b.category||'')}${field('publisher','Nhà xuất bản',b.publisher||'','text',false)}${field('publication_year','Năm xuất bản',b.publication_year||new Date().getFullYear(),'number',true,'min="1000" max="2100"')}${b.id?select('status','Trạng thái',{ACTIVE:'Hoạt động',WITHDRAWN:'Ngừng lưu hành'},b.status):''}<label class="full">Mô tả<textarea name="description" maxlength="5000">${esc(b.description||'')}</textarea></label></div><p class="error" role="alert"></p><button>Lưu đầu sách</button></form>`);
 bindForm('book-form',async d=>{d.publication_year=Number(d.publication_year);d.authors=d.authors.split(',').map(x=>x.trim()).filter(Boolean);if(b.id)d.id=b.id;const r=await api('book',d);toast('Đã lưu đầu sách.');go('book/'+r.id);});
};
async function copiesView(id){
 const {book:b,copies}=await api('book?id='+id);window.currentBook={book:b,copies};
 show('Bản sao sách',b.title,`<div class="tabs"><button class="selected" data-ui="copy-filter" data-id="all">Tất cả (${copies.length})</button><button data-ui="copy-filter" data-id="available">Sẵn sàng (${copies.filter(c=>c.status==='AVAILABLE').length})</button></div><div id="copy-list" class="screen-grid stack">${copies.map(c=>copyCard(c)).join('')}</div>${btn('Thêm bản sao','new-copy',id,'')}<p class="muted">Mỗi bản sao có một mã vạch riêng để theo dõi mượn trả.</p>`);
}
function copyCard(c){return card(c.barcode,`<p class="muted">Mã vạch · ${esc(c.location)}</p>${facts([['Trạng thái',badge(c.status)]])}${uiButton('Chỉnh sửa','copy-edit',c.id)}`);}
dashboardView=async function(version){
 const [r,history]=await Promise.all([api('dashboard'),api('history')]);if(version!==viewVersion)return;
 const name=me.profile.full_name.trim().split(/\s+/).pop();
 show('Chào '+name+',',new Date().toLocaleDateString('vi-VN',{weekday:'long',day:'numeric',month:'long'})+' · '+roles[me.role],
 card('Hôm nay tại thư viện',facts([['Phiếu mượn mới',`<span class="blue">${r.new_loans}</span>`],['Sách cần nhận trả',`<span class="blue">${r.open}</span>`],['Sách đang quá hạn',`<span class="bad">${r.overdue}</span>`]]))+
 routeLink('Lập phiếu mượn','checkout',true)+routeLink('Nhận trả sách','return')+
 (r.overdue?msg('Cần xử lý',`<p>${r.overdue} độc giả/bản sao có sách quá hạn. Cần nhắc trả hoặc xem chi tiết để hỗ trợ.</p>`,'warning'):msg('Không có sách quá hạn','<p>Dữ liệu được cập nhật từ các phiếu mượn.</p>'))+
 '<h2 class="subheading">Lối tắt</h2>'+routeLink('Độc giả & thẻ thư viện','members')+routeLink('Báo cáo hoạt động','reports')+routeLink('Đặt trước & tiền phạt','reservations')+(admin()?routeLink('Kho sách','catalog')+routeLink('Mượn & trả','loans'):''));
};
loansView=async function(version){
 const rows=await api('history');if(version!==viewVersion)return;window.historyRows=rows;
 if(!staff())return myLoans(rows);
 const groups=Object.values(rows.reduce((out,r)=>{(out[r.loan_id]??=[]).push(r);return out;},{}));
 const filtered=groups.filter(g=>{const active=g.some(r=>r.status==='OPEN'),late=g.some(overdue);return (loanFilter==='OPEN'?active:loanFilter==='late'?late:!active)&&[g[0].full_name,code('PM',g[0].loan_id),code('DG',g[0].member_id),...g.map(r=>r.barcode)].join(' ').toLowerCase().includes(loanSearch.toLowerCase());});
 show('Mượn & trả','Theo dõi phiếu và hạn trả',`<form id="loan-search">${field('q','Tìm mã phiếu hoặc độc giả',loanSearch,'search',false)}<button class="visually-hidden">Tìm</button></form>${tabs([['OPEN','Đang mượn'],['late','Quá hạn'],['RETURNED','Đã trả']],loanFilter,'loan-filter')}<div class="screen-grid stack">${filtered.map(g=>{const r=g[0],late=g.find(overdue);return `<button type="button" class="card linked-card" data-ui="loan" data-id="${r.loan_id}" ><h2>${code('PM',r.loan_id)}</h2><p class="muted">${esc(r.full_name)} · ${code('DG',r.member_id)}</p>${facts([['Hạn trả',day(r.due_date)],['Trạng thái',late?`<span class="bad">Trễ ${lateDays(late.due_date)} ngày</span>`:g.some(r=>r.status==='OPEN')?`<span class="blue">${g.filter(r=>r.status==='OPEN').length} quyển chưa trả</span>`:'Đã trả']])}</button>`;}).join('')||empty('Không có phiếu phù hợp')}</div>${routeLink('Lập phiếu mượn','checkout',true)}${routeLink('Nhận trả sách','return')}`);
 bindForm('loan-search',async d=>{loanSearch=d.q;await render();});
};
async function myLoans(rows){
 const summary=await api('member-summary');
 const open=rows.filter(r=>r.status==='OPEN'),late=open.filter(overdue);
 show('Sách của tôi',`${me.profile.full_name} · ${code('DG',me.profile.id)}`,tabs([['OPEN',`Đang mượn (${open.length})`],['RETURNED','Lịch sử']],loanFilter==='late'?'OPEN':loanFilter,'loan-filter')+
 msg(`Bạn đang mượn ${summary.open_count} / ${summary.limit} quyển`,`<p>${summary.overdue_details.length?`${summary.overdue_details.length} bản quá hạn`:'Chưa có sách quá hạn'} · Dư nợ: ${money(summary.balance)}</p>`,late.length?'warning':'good')+
 (loanFilter==='RETURNED'?rows.filter(r=>r.status==='RETURNED'):open).map(r=>`<label class="book-card"><input type="checkbox" data-renew="${r.id}" ${selectedRenew.has(r.id)?'checked':''} ${r.status!=='OPEN'?'disabled':''} class="renew-box"><img src="/cover.png" alt="Bìa ${esc(r.title)}"><span><strong>${esc(r.title)}</strong><small>Hạn trả: ${day(r.due_date)}</small><small class="${overdue(r)?'bad':'good'}">${overdue(r)?'Trễ '+lateDays(r.due_date)+' ngày':'Còn '+Math.max(0,Math.ceil((new Date(r.due_date)-Date.now())/86400000))+' ngày'}</small></span></label>`).join('')+
 (loanFilter!=='RETURNED'?uiButton('Gia hạn sách đã chọn','renew-selected'):'')+card('Điều kiện gia hạn','<p class="muted">Chưa quá hạn, còn lượt gia hạn và không có độc giả đang chờ.</p>')+routeLink('Khám phá thêm sách','catalog')+routeLink('Tiền phạt của tôi','fines'));
}
checkoutForm=function(){
 if(!draft)draft={member:null,copies:[],request_key:key()};
 show('Lập phiếu mượn','Bước 1/2 · Chọn độc giả & sách',`<form id="member-lookup" class="stack">${field('query','Mã thẻ / số điện thoại',draft.member?code('DG',draft.member.id):'')}<button class="secondary">Kiểm tra độc giả</button><p class="error" role="alert"></p></form><div id="member-check" class="stack"></div><form id="copy-scan" class="stack">${field('barcode','Quét / nhập mã vạch sách')}<button class="secondary">Thêm sách vào phiếu</button><p class="error" role="alert"></p></form><div id="cart" class="stack"></div>${uiButton('Tiếp tục · '+draft.copies.length+' quyển','checkout-next','',true)}<p class="muted">Phiếu chỉ được lưu khi xác nhận ở bước tiếp theo.</p>`);
 bindForm('member-lookup',async d=>{const q=d.query.trim(),id=/^(DG-)?0*(\d+)$/i.exec(q);const all=await api('members?q='+encodeURIComponent(id?'':q));const matches=id?all.filter(m=>m.id===Number(id[2])):all;if(matches.length!==1)throw new Error(matches.length?'Có nhiều độc giả phù hợp. Hãy nhập mã thẻ chính xác.':'Không tìm thấy độc giả.');draft.member=matches[0];await updateCart();});
 bindForm('copy-scan',async d=>{if(!draft.member)throw new Error('Hãy kiểm tra độc giả trước.');if(draft.copies.some(c=>c.barcode===d.barcode.trim()))throw new Error('Bản sao đã có trong phiếu.');const c=await api('lookup-copy?barcode='+encodeURIComponent(d.barcode.trim()));if(!['AVAILABLE','HELD'].includes(c.status))throw new Error('Bản sao không sẵn sàng cho mượn.');draft.copies.push(c);$('#copy-scan').reset();await updateCart();});
 $('[data-ui="checkout-next"]').disabled=!draft.member||!draft.eligible||!draft.copies.length;
 if(draft.member)updateCart().catch(e=>toast(errorMessage(e)));
};
async function updateCart(){
 const m=draft.member,e=await api(`eligibility?member_id=${m.id}&count=${Math.max(1,draft.copies.length)}`);draft.eligible=e.eligible;
 setTitle(e.eligible?'Lập phiếu mượn':'Chưa thể cho mượn',e.eligible?'Bước 1/2 · Chọn độc giả & sách':'Kết quả kiểm tra điều kiện');
 $('#copy-scan').hidden=!e.eligible;
 $('#member-check').innerHTML=msg(m.full_name,`<p>${code('DG',m.id)} · Thẻ ${m.status==='ACTIVE'?'đang hoạt động':'ngừng hoạt động'}</p><p><strong>${e.eligible?'Đủ điều kiện mượn':'Chưa thể cho mượn'}</strong></p>`+facts([['Đang mượn / Giới hạn',`${e.open_count} / ${e.limit} quyển`],['Sách quá hạn',e.overdue_details.length],['Dư nợ phạt',money(e.balance)]]),e.eligible?'good':'bad')+
 (!e.eligible?msg(e.overdue_details.length?'Có sách chưa trả quá hạn':'Chưa đủ điều kiện',`<p>${e.overdue_details.length?'Cần hoàn tất trả sách quá hạn trước khi lập phiếu mượn mới.':'Kiểm tra trạng thái thẻ, dư nợ và giới hạn mượn.'}</p>`,'bad')+msg('Vẫn có thể nhận trả sách','<p>Việc bị chặn mượn không ngăn độc giả trả sách.</p>','warning')+routeLink('Chuyển sang nhận trả','return'):'');
 $('#cart').innerHTML=draft.copies.map((c,i)=>card(c.title,`<p class="muted">${esc(c.barcode)} · ${esc(c.location)}</p>${uiButton('Bỏ khỏi phiếu','remove-copy',i)}`)).join('');
 const next=$('[data-ui="checkout-next"]');next.disabled=!e.eligible||!draft.copies.length;next.textContent=`Tiếp tục · ${draft.copies.length} quyển`;
}
async function checkoutConfirm(){
 if(!draft?.member||!draft.copies.length){go('checkout');return;}
 const e=await api(`eligibility?member_id=${draft.member.id}&count=${draft.copies.length}`);if(!e.eligible){go('checkout');return;}
 const policy=await api('loan-policy'),due=new Date(Date.now()+policy.loan_days*86400000);
 show('Xác nhận cho mượn','Bước 2/2 · Kiểm tra trước khi lưu',card(draft.member.full_name,`<p class="muted">${code('DG',draft.member.id)} · Đủ điều kiện</p>`+facts([['Ngày mượn',day(new Date())],['Hạn trả',`<span class="blue">${day(due)}</span>`]]))+draft.copies.map(c=>bookTile(c,`<small>Mã bản sao: ${esc(c.barcode)}</small><span class="good">Nguyên: Tình trạng tốt</span>`,false)).join('')+card('Kiểm tra lại sách bàn giao','<p class="muted">Phiếu được lưu sau khi xác nhận. Lịch sử phiếu đã xác nhận được giữ lại.</p>')+uiButton('Xác nhận cho mượn','checkout-save','',true)+routeLink('Quay lại chỉnh sửa','checkout'));
}
async function loanDetail(id,success=false){
 success=success||successLoanId===id;
 const rows=(await api('history')).filter(r=>r.loan_id===id);if(!rows.length)throw new Error('Không tìm thấy phiếu mượn.');const r=rows[0];
 show('Chi tiết phiếu mượn',code('PM',id)+' · '+(rows.some(r=>r.status==='OPEN')?'Đã xác nhận':'Đã trả'),(success?msg('Cho mượn thành công',`<p>Đã ghi nhận ${rows.length} quyển cho ${esc(r.full_name)}.</p>`):'')+card('Thông tin phiếu',facts([['Độc giả',`${esc(r.full_name)} · ${code('DG',r.member_id)}`],['Ngày mượn',day(r.loan_date)],['Hạn trả',day(r.due_date)],['Thủ thư',esc(r.staff_name||'')]]))+rows.map(r=>bookTile(r,`<small>${esc(r.barcode)}</small>${badge(r.status)}`,false)+(r.status==='OPEN'&&staff()?routeLink('Nhận trả sách','return/'+encodeURIComponent(r.barcode),true):'')).join('')+routeLink('Về danh sách phiếu','loans'));
}
returnForm=function(barcode=''){
 show('Nhận trả sách','Quét mã vạch bản sao cần nhận lại',`<form id="return-scan" class="stack">${field('barcode','Quét mã vạch bản sao',barcode)}<p class="error" role="alert"></p><button>Kiểm tra sách trả</button></form><p class="muted">Tiền phạt được ghi nhận khi xác nhận trả. Luôn có thể nhận sách từ độc giả bị chặn mượn.</p>`);
 bindForm('return-scan',async d=>{returnState={...await api('return-preview?barcode='+encodeURIComponent(d.barcode)),request_key:key()};go('return-preview');});
 if(barcode)$('#return-scan').requestSubmit();
};
function returnPreview(){
 if(!returnState){go('return');return;}const r=returnState;
 show('Nhận trả sách',`${esc(r.full_name)} · ${esc(r.barcode)}`,field('barcode','Quét mã vạch bản sao',r.barcode,'text',false,'readonly')+card(r.title,`<p class="muted">${esc(r.barcode)} · Đã chọn nhận trả</p>`+facts([['Hạn trả',day(r.due_date)],['Ngày trả',day(r.return_date)],['Số ngày quá hạn',`<span class="bad">${r.overdue_days} ngày</span>`]]))+card('Phạt trễ hạn dự kiến',facts([...r.breakdown.days.map((n,i)=>['Bậc '+(i+1)+' · '+n+' ngày',money(r.breakdown.amounts[i])]),['Tổng phạt',`<span class="bad">${money(r.fine)}</span>`]])+'<p class="muted">Theo chính sách áp dụng khi mượn. Số tiền được tính lại khi xác nhận.</p>')+`<form id="return-confirm" class="stack">${select('condition','Tình trạng nhận lại',{AVAILABLE:'Tốt, có thể cho mượn',DAMAGED:'Hư hỏng',LOST:'Thất lạc'})}<p class="error" role="alert"></p><button>Xác nhận trả · 1 quyển</button></form>`);
 bindForm('return-confirm',async d=>{const result=await api('return',{barcode:r.barcode,condition:d.condition,request_key:r.request_key});receipt={returnResult:result,barcode:r.barcode,when:new Date().toISOString()};if(result.fine_id)go('pay/'+result.fine_id);else go('receipt');});
}
payForm=async function(id){
 const rows=await api('fines'),f=rows.find(r=>r.id===id);if(!f)throw new Error('Không tìm thấy khoản phạt.');
 if(receipt?.returnResult?.fine_id!==id)receipt=null;
 show('Thanh toán tiền phạt',`${code('PF',f.id)} · ${f.full_name}`,card('Dư nợ cần thu',`<div class="metric">${money(f.balance)}</div>`+facts([['Phạt đã ghi nhận',money(f.amount)],['Đã thanh toán',money(f.paid)]]))+`<form id="payment-form" class="stack">${field('amount','Số tiền thu',f.balance,'number',true,`min="1" max="${f.balance}" step="1"`)}${select('method','Phương thức',{CASH:'Tiền mặt',TRANSFER:'Chuyển khoản'})}${card('Đối chiếu trước khi thu','<p class="muted">Số tiền phải lớn hơn 0 và không vượt quá dư nợ.</p>')}<p class="error" role="alert"></p><button ${f.balance===0?'disabled':''}>Xác nhận thu ${money(f.balance)}</button></form>${routeLink('Thu sau','receipt')}`);
 $('#payment-form input[name="amount"]').addEventListener('input',event=>{$('#payment-form button').textContent='Xác nhận thu '+money(event.target.value||0);});
 bindForm('payment-form',async(d,form)=>{const r=await api('payment',{fine_id:f.id,amount:Number(d.amount),method:d.method,request_key:form.dataset.requestKey});receipt={...receipt,payment:r,method:d.method,barcode:f.barcode,when:new Date().toISOString()};go('receipt');});
};
function receiptView(){
 if(!receipt){go('loans');return;}const r=receipt,p=r.payment;
 show(r.returnResult?'Đã nhận trả sách':'Biên nhận thanh toán','Giao dịch đã được ghi nhận',msg(r.returnResult?'Trả sách thành công':'Thanh toán thành công',`<p>${r.returnResult?'Bản sao '+esc(r.barcode)+' đã được nhận lại.':'Đã lưu giao dịch thu tiền.'}</p>`)+
 (p?card('Biên nhận thanh toán',facts([['Mã thanh toán',code('TT',p.payment_id)],['Ngày thu',day(r.when)],['Số tiền đã thu',`<span class="good">${money(p.amount)}</span>`],['Dư nợ còn lại',money(p.balance)],['Phương thức',r.method==='CASH'?'Tiền mặt':'Chuyển khoản']])):card('Thông tin trả sách',facts([['Mã bản sao',esc(r.barcode)],['Tiền phạt',money(r.returnResult?.fine||0)]])))+routeLink('Về danh sách phiếu','loans',true)+routeLink('Xem lịch sử giao dịch','transactions'));
}
reservationsView=async function(version){
 const rows=await api('reservations');if(version!==viewVersion)return;
 show(staff()?'Quản lý đặt trước':'Đặt trước của tôi','Theo dõi hàng chờ nhận sách',rows.map(r=>`<div class="screen-stack">${r.status==='READY'?msg(r.title,`<p>Đã sẵn sàng · Giữ đến ${day(r.expires_at)}</p><p>Đến quầy thư viện và xuất trình mã thẻ để nhận sách.</p><p>${esc(r.barcode||'')}</p>`):card(r.title,`<p class="muted">${esc(statuses[r.status])}${r.status==='WAITING'?' · Vị trí số '+r.queue_position:''}</p>${staff()?`<p class="muted">${esc(r.full_name)}</p>`:''}`)}${['WAITING','READY'].includes(r.status)?uiButton('Hủy đặt trước','cancel-start',r.id):''}</div>`).join('')+(!rows.length?empty('Chưa có yêu cầu đặt trước','Chọn một đầu sách đã hết bản sẵn sàng để đặt trước.'):'')+card('Sách được giữ theo thứ tự','<p class="muted">Nếu hết hạn nhận, bản sao sẽ được chuyển cho độc giả tiếp theo.</p>'));
};
reportsView=async function(){
 const now=new Date(),local=d=>`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
 show('Báo cáo hoạt động','Số liệu được tổng hợp từ giao dịch thực tế',`<form id="report-form" class="stack"><div class="form-grid">${field('start','Từ ngày',local(new Date(now.getFullYear(),now.getMonth(),1)),'date')}${field('end','Đến ngày',local(now),'date')}</div><button class="secondary">Xem kỳ báo cáo</button><p class="error" role="alert"></p></form><div id="report-result" class="stack"></div>`);
 bindForm('report-form',async d=>{const end=new Date(d.end+'T00:00:00');end.setDate(end.getDate()+1);const q=`start=${encodeURIComponent(new Date(d.start+'T00:00:00').toISOString())}&end=${encodeURIComponent(end.toISOString())}`,r=await api('report?'+q);
 $('#report-result').innerHTML=card('Tổng quan',facts([['Lượt mượn',r.borrowed],['Sách đã trả trong kỳ',r.returned],['Sách chưa trả của kỳ',r.open],['Trong đó quá hạn',`<span class="bad">${r.overdue}</span>`],['Tiền đã thu',money(r.collected)]]))+card('Lượt mượn theo thể loại',r.by_category.map(g=>`<div class="status-row"><span>${esc(g.category)}</span><span>${g.borrowed}</span></div><meter class="bar" min="0" max="${Math.max(1,r.borrowed)}" value="${g.borrowed}" aria-label="${esc(g.category)}"></meter>`).join('')+`<p class="muted">Tổng: ${r.borrowed} lượt mượn</p>`)+`<details class="card"><summary>Xem chi tiết báo cáo</summary><h3>Tiền đã thu</h3>${table(['Mã','Độc giả','Ngày thu','Số tiền'],r.payments.map(p=>[code('TT',p.id),esc(p.full_name),day(p.paid_at),money(p.amount)]))}<h3>Tồn kho hiện tại</h3>${r.inventory.map(i=>`<p>${esc(statuses[i.status])}: ${i.quantity}</p>`).join('')}<a href="/api/report.csv?${esc(q)}" download>Xuất CSV</a></details>`;
 });$('#report-form').requestSubmit();
};
accountsView=async function(version){
 const rows=await api('accounts');if(version!==viewVersion)return;window.accountRows=rows;
 const filtered=rows.filter(a=>a.role===accountFilter&&`${a.full_name} ${a.email} ${a.username}`.toLowerCase().includes(accountSearch.toLowerCase()));
 show('Tài khoản & quyền','Quản trị hệ thống',`<form id="account-search">${field('q','Tìm họ tên hoặc email',accountSearch,'search',false)}<button class="visually-hidden">Tìm</button></form>${tabs([['MEMBER','Độc giả'],['LIBRARIAN','Thủ thư'],['ADMINISTRATOR','Quản trị']],accountFilter,'account-filter')}<div class="screen-grid stack">${filtered.map(a=>card(a.full_name||a.username,`<p class="muted">${esc(a.email)}</p>`+facts([['Vai trò',esc(roles[a.role])],['Trạng thái',badge(a.status)]])+btn('Chỉnh sửa','edit-account',a.id))).join('')||empty('Không có tài khoản phù hợp')}</div>${btn('Tạo tài khoản','new-account','','')}<p class="muted">Khóa tài khoản khi ngừng sử dụng. Giữ lại lịch sử mượn trả và thanh toán.</p>`);
 bindForm('account-search',async d=>{accountSearch=d.q;await render();});
};
profileView=async function(){
 me=await api('me');const p=me.profile;
 show('Cá nhân','Thông tin & công việc',card(p.full_name,`<p class="muted">${esc(roles[me.role])} · ${code(staff()?'ST':'DG',p.id)}</p>`+facts([['Email',esc(me.email)],['Điện thoại',esc(p.phone||'Chưa cập nhật')]]))+routeLink('Chỉnh sửa thông tin','profile-edit')+uiButton('Đổi mật khẩu','password')+(staff()?routeLink('Quản lý độc giả','members')+routeLink('Báo cáo hoạt động','reports')+routeLink('Đặt trước','reservations')+routeLink('Tiền phạt','fines'):'')+btn('Đăng xuất','logout')+'<p class="muted">LIBRARY · Quản lý thư viện<br>Phiên bản thiết kế 2.0</p>');
};
document.addEventListener('change',e=>{if(e.target.matches('[data-renew]')){const id=Number(e.target.dataset.renew);e.target.checked?selectedRenew.add(id):selectedRenew.delete(id);}});
document.addEventListener('click',async e=>{
 const b=e.target.closest('[data-ui]');if(!b)return;e.preventDefault();e.stopImmediatePropagation();if(b.disabled)return;b.disabled=true;
 try{const id=b.dataset.id;switch(b.dataset.ui){
 case'book':go('book/'+id);break;case'loan':go('loan/'+id);break;
 case'book-filter':bookFilter=id;page=1;await render();break;case'loan-filter':loanFilter=id;await render();break;case'account-filter':accountFilter=id;await render();break;
 case'copy-filter':$('#copy-list').innerHTML=window.currentBook.copies.filter(c=>id==='all'||c.status==='AVAILABLE').map(copyCard).join('');document.querySelectorAll('[data-ui="copy-filter"]').forEach(x=>x.classList.toggle('selected',x.dataset.id===id));break;
 case'copy-edit':copyForm(window.currentBook.book.id,window.currentBook.copies.find(c=>c.id===Number(id)));break;
 case'remove-copy':draft.copies.splice(Number(id),1);await updateCart();break;
 case'checkout-next':go('checkout-confirm');break;
 case'checkout-save':{const r=await api('checkout',{member_id:draft.member.id,barcodes:draft.copies.map(c=>c.barcode),request_key:draft.request_key});draft=null;successLoanId=r.loan_id;go('loan/'+r.loan_id);break;}
 case'renew-selected':{if(!selectedRenew.size)throw new Error('Hãy chọn ít nhất một quyển sách.');const failures=[];for(const id of selectedRenew){try{await api('renew',{detail_id:id,request_key:key()});}catch(err){failures.push(errorMessage(err));}}selectedRenew.clear();await render();toast(failures.length?failures.join('; '):'Gia hạn thành công.');break;}
 case'password':oldProfileView();setTimeout(()=>$('#password-form input')?.focus(),0);break;
 case'cancel-start':modal('Hủy đặt trước?',`<p>Yêu cầu sẽ được hủy và sách được chuyển cho độc giả tiếp theo nếu có.</p><form id="cancel-form" class="stack"><p class="error" role="alert"></p><button>Xác nhận hủy</button></form>`);bindForm('cancel-form',async()=>{await api('cancel-reservation',{id:Number(id)});close();toast('Đã hủy đặt trước.');await render();});break;
 }}catch(err){toast(errorMessage(err));}finally{if(b.isConnected)b.disabled=false;}
},true);
window.addEventListener('resize',navigation);
// Existing supplemental dialogs return to the matching full screen after saving.
copyForm=function(bookId,c={}){
 modal(c.id?'Chỉnh sửa bản sao':'Thêm bản sao',`<form id="copy-form" class="stack">${field('barcode','Mã vạch riêng',c.barcode||'')}${field('location','Vị trí trên kệ',c.location||'')}${select('status','Trạng thái',{AVAILABLE:'Sẵn sàng',DAMAGED:'Hư hỏng',LOST:'Thất lạc',WITHDRAWN:'Ngừng lưu hành'},c.status)}<p class="error" role="alert"></p><button>Lưu bản sao</button></form>`);
 bindForm('copy-form',async d=>{d.book_id=Number(bookId);if(c.id)d.id=c.id;await api('copy',d);close();toast('Đã lưu bản sao.');go('copies/'+bookId);});
};

(async()=>{try{me=await api("me");}catch{me=null;}await render();})();

async function transactionsView(){
 const rows=await api('payments');
 show('Lịch sử giao dịch','Các biên nhận thanh toán đã được lưu',
 rows.map(p=>card(code('TT',p.id),'<p class="muted">'+esc(p.full_name)+'</p>'+facts([
 ['Ngày thu',day(p.paid_at)],['Số tiền',money(p.amount)],['Phương thức',p.method==='CASH'?'Tiền mặt':'Chuyển khoản'],['Phiếu phạt',code('PF',p.fine_id)]
 ]))).join('')||empty('Chưa có giao dịch thu tiền'));
}

const originalFinesView=finesView;
finesView=async function(version){
 await originalFinesView(version);
 document.getElementById('content').insertAdjacentHTML('beforeend',routeLink('Lịch sử giao dịch','transactions'));
};
