# Контракт API

| Метод и путь | Параметры | Успешный ответ | Ошибки |
|---|---|---|---|
| POST /api/login | username, password: непустые строки | 200: id, username, display_name, is_staff; cookie | 422 неверный JSON; 401 неверные данные; 503 база не наполнена |
| POST /api/logout | нет | 200: {ok:true} | 401 |
| GET /api/categories | нет | 200: {items:[{id,name,norm_minutes}]} | 401 |
| GET /api/tickets | page≥1, size 1..100; status new/in_progress/closed; category_id≥1 | 200: items, total, page, size | 401, 422 |
| GET /api/tickets/{id} | id: целое ≥0 | 200: {ticket,comments}; ticket содержит category, norm_minutes, reaction_seconds, sla_breached | 401, 404 |
| POST /api/tickets | title, body: непустые строки ≤5000; category_id целое >0 | 201: объект заявки | 401, 422, 404 категория |
| POST /api/tickets/{id}/comments | body: непустая строка ≤5000 | 201: id,ticket_id,user_id,body,created_at | 401, 422, 404, 409 закрыта |
| PATCH /api/tickets/{id}/status | status: new/in_progress/closed | 200: объект заявки | 401, 422, 404, 409 недопустимый переход |
| GET /api/summary | нет | 200: {total_tickets,categories:[{category_id,name,open,breached,breached_share}]} | 401 |

Объект заявки: id, user_id, category_id, title, body, status, created_at, updated_at. В списке добавлены display_name и category; в карточке также norm_minutes, reaction_seconds (null, если ответа нет) и sla_breached.
Комментарий карточки дополнен display_name и is_staff. Список: ID по убыванию; комментарии: created_at и ID по возрастанию. Пустая или вышедшая за конец страница: items=[] с общим total. Несуществующая категория в фильтре даёт пустой список.
Переходы разрешены только new → in_progress → closed. Повторный переход и открытие закрытой заявки запрещены. Ответы сотрудника определяются users.is_staff; первый — минимум времени таких комментариев. Нарушение: время реакции строго больше norm_minutes*60; равенство не считается нарушением. При отсутствии ответа для нарушения используется текущее UTC-время; у закрытых заявок SLA показывается в карточке, но они исключены из числа открытых сводки. Доля в категории: breached/open, при open=0 равна 0.

GET / — HTML клиента (200, без авторизации); измерения контракта относятся к девяти операциям API. Неверный URL/метод обрабатывает Flask (404/405).
