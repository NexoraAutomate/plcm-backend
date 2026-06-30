# PLCM API - Quick Reference Guide

**Base URL:** `http://127.0.0.1:8000/api`

## Quick Endpoint Summary

### CRUD Operations Pattern
All resources follow this pattern:
```
POST   /{resource}/              → Create
GET    /{resource}/              → List (with pagination)
GET    /{resource}/{id}/         → Get one
PUT    /{resource}/{id}/         → Update
DELETE /{resource}/{id}/         → Delete
```

## All Endpoints at a Glance

| Resource | Create | List | Get | Update | Delete | Related |
|----------|--------|------|-----|--------|--------|---------|
| **Users** | POST `/users/` | GET `/users/` | GET `/users/{id}/` | PUT `/users/{id}/` | DELETE `/users/{id}/` | GET `/users/{id}/projects/` |
| **Customers** | POST `/customers/` | GET `/customers/` | GET `/customers/{id}/` | PUT `/customers/{id}/` | DELETE `/customers/{id}/` | GET `/customers/{id}/orders/` |
| **Orders** | POST `/orders/` | GET `/orders/` | GET `/orders/{id}/` | PUT `/orders/{id}/` | DELETE `/orders/{id}/` | GET `/orders/{id}/projects/` |
| **Projects** | POST `/projects/` | GET `/projects/` | GET `/projects/{id}/` | PUT `/projects/{id}/` | DELETE `/projects/{id}/` | GET `/projects/{id}/systems/` |
| **Systems** | POST `/systems/` | GET `/systems/` | GET `/systems/{id}/` | PUT `/systems/{id}/` | DELETE `/systems/{id}/` | GET `/systems/{id}/subsystems/` |
| **Subsystems** | POST `/subsystems/` | GET `/subsystems/` | GET `/subsystems/{id}/` | PUT `/subsystems/{id}/` | DELETE `/subsystems/{id}/` | GET `/subsystems/{id}/modules/` |
| **Modules** | POST `/modules/` | GET `/modules/` | GET `/modules/{id}/` | PUT `/modules/{id}/` | DELETE `/modules/{id}/` | GET `/modules/{id}/units/` |
| **Units** | POST `/units/` | GET `/units/` | GET `/units/{id}/` | PUT `/units/{id}/` | DELETE `/units/{id}/` | GET `/units/{id}/components/` |
| **Components** | POST `/components/` | GET `/components/` | GET `/components/{id}/` | PUT `/components/{id}/` | DELETE `/components/{id}/` | GET `/components/{id}/inventory/` |
| **Inventory** | POST `/inventory/` | GET `/inventory/` | GET `/inventory/{id}/` | PUT `/inventory/{id}/` | DELETE `/inventory/{id}/` | - |
| **Statuses** | POST `/statuses/` | GET `/statuses/` | GET `/statuses/{id}/` | PUT `/statuses/{id}/` | DELETE `/statuses/{id}/` | - |
| **Entities** | POST `/entities/` | GET `/entities/` | GET `/entities/{id}/` | PUT `/entities/{id}/` | DELETE `/entities/{id}/` | GET `/entities/{id}/status-history/`<br>GET `/entities/{id}/maintenance-logs/` |
| **Status History** | POST `/entity-status-history/` | GET `/entity-status-history/` | GET `/entity-status-history/{id}/` | PUT `/entity-status-history/{id}/` | DELETE `/entity-status-history/{id}/` | - |
| **Maintenance Logs** | POST `/maintenance-logs/` | GET `/maintenance-logs/` | GET `/maintenance-logs/{id}/` | PUT `/maintenance-logs/{id}/` | DELETE `/maintenance-logs/{id}/` | - |

## Common Request Templates

### CREATE Request
```javascript
async function create(resource, data) {
  const response = await fetch(`http://127.0.0.1:8000/api/${resource}/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  return response.json();
}

// Usage
const newUser = await create('users', {
  username: 'john.doe',
  email: 'john@example.com',
  full_name: 'John Doe',
  is_active: true
});
```

### LIST Request with Pagination
```javascript
async function list(resource, skip = 0, limit = 10) {
  const response = await fetch(
    `http://127.0.0.1:8000/api/${resource}/?skip=${skip}&limit=${limit}`
  );
  return response.json();
}

// Usage
const users = await list('users', 0, 10);
```

### GET Request
```javascript
async function get(resource, id) {
  const response = await fetch(`http://127.0.0.1:8000/api/${resource}/${id}/`);
  if (!response.ok) {
    throw new Error(`Resource not found: ${resource}/${id}`);
  }
  return response.json();
}

// Usage
const user = await get('users', 1);
```

### UPDATE Request
```javascript
async function update(resource, id, data) {
  const response = await fetch(`http://127.0.0.1:8000/api/${resource}/${id}/`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  return response.json();
}

// Usage
const updated = await update('users', 1, {
  email: 'newemail@example.com'
});
```

### DELETE Request
```javascript
async function delete_(resource, id) {
  const response = await fetch(`http://127.0.0.1:8000/api/${resource}/${id}/`, {
    method: 'DELETE'
  });
  return response.json();
}

// Usage
const result = await delete_('users', 1);
```

## Common Field Requirements

### User Create/Update
```json
{
  "username": "string (required for create)",
  "email": "string (optional)",
  "full_name": "string (optional)",
  "is_active": "boolean (optional, default: true)"
}
```

### Project Create/Update
```json
{
  "name": "string (required for create)",
  "description": "string (optional)",
  "start_date": "ISO datetime (required for create)",
  "end_date": "ISO datetime (optional)",
  "owner_id": "integer (required for create)",
  "order_id": "integer (optional)",
  "status_id": "integer (optional)"
}
```

### Component Create/Update
```json
{
  "name": "string (required for create)",
  "description": "string (optional)",
  "sku": "string (optional)",
  "unit_id": "integer (required for create)",
  "status_id": "integer (optional)"
}
```

### Inventory Create/Update
```json
{
  "component_id": "integer (required for create)",
  "quantity": "integer (required for create)",
  "location": "string (optional)"
}
```

## Hierarchy Structure

```

├──Customer
  ├──Orders (many)
  │  ├── Projects (many)
  │  │  ├── Systems (many)
  │  │  │  ├── Subsystems (many)
  │  │  │  │  ├── Modules (many)
  │  │  │  │  │  ├── Units (many)
  │  │  │  │  │  │   ├── Components (many)
  │  │  │  │  │  │   └── Inventory Items (many)

Order
└── Projects (many)

Customer
└── Orders (many)

Entity
├── Status History (many)
└── Maintenance Logs (many)
```

## HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 204 | No Content |
| 400 | Bad Request (validation error) |
| 404 | Not Found |
| 422 | Validation Error (missing/invalid fields) |
| 500 | Internal Server Error |

## Error Response Example

```javascript
// 404 Error
{
  "detail": "User not found"
}

// 422 Validation Error
{
  "detail": [
    {
      "loc": ["body", "username"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

## Testing Endpoints

### Using cURL

```bash
# Create a user
curl -X POST http://127.0.0.1:8000/api/users/ \
  -H "Content-Type: application/json" \
  -d '{"username":"john","email":"john@example.com","full_name":"John","is_active":true}'

# List users with pagination
curl "http://127.0.0.1:8000/api/users/?skip=0&limit=10"

# Get a user
curl http://127.0.0.1:8000/api/users/1/

# Update a user
curl -X PUT http://127.0.0.1:8000/api/users/1/ \
  -H "Content-Type: application/json" \
  -d '{"email":"newemail@example.com"}'

# Delete a user
curl -X DELETE http://127.0.0.1:8000/api/users/1/
```

### Using Postman or Insomnia

1. Import the endpoints as shown in the table above
2. Set base URL to `http://127.0.0.1:8000/api`
3. Use JSON body for POST/PUT requests
4. Add query parameters `?skip=0&limit=10` for list endpoints

## API Documentation Interface

For interactive API testing and full schema documentation, visit:
```
http://127.0.0.1:8000/docs
```

This provides a Swagger UI where you can:
- View all endpoints
- Test endpoints in real-time
- See request/response schemas
- Check parameter requirements

## React Example

```javascript
// useAPI hook
const useAPI = (url, method = 'GET', body = null) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        const options = {
          method,
          headers: { 'Content-Type': 'application/json' }
        };
        if (body) options.body = JSON.stringify(body);
        
        const response = await fetch(`http://127.0.0.1:8000/api${url}`, options);
        if (!response.ok) throw new Error('API Error');
        const result = await response.json();
        setData(result);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };
    
    fetchData();
  }, [url]);

  return { data, loading, error };
};

// Usage
function UsersList() {
  const { data: users, loading, error } = useAPI('/users/?skip=0&limit=10');
  
  if (loading) return <div>Loading...</div>;
  if (error) return <div>Error: {error}</div>;
  
  return (
    <ul>
      {users?.map(user => (
        <li key={user.id}>{user.full_name} ({user.username})</li>
      ))}
    </ul>
  );
}
```

## Vue Example

```javascript
// API service
const API_BASE = 'http://127.0.0.1:8000/api';

export const apiService = {
  async get(endpoint) {
    const response = await fetch(`${API_BASE}${endpoint}`);
    return response.json();
  },
  
  async post(endpoint, data) {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    return response.json();
  },
  
  async put(endpoint, data) {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    return response.json();
  },
  
  async delete(endpoint) {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      method: 'DELETE'
    });
    return response.json();
  }
};

// Usage in component
export default {
  data() {
    return { users: [] };
  },
  async mounted() {
    this.users = await apiService.get('/users/?skip=0&limit=10');
  }
};
```

---

**Last Updated:** February 23, 2026  
**API Version:** 1.0
