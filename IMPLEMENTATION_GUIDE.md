# PLCM API - Implementation Guide for Frontend

This guide provides practical code examples using different technologies to interact with the PLCM API.

## Table of Contents
- [JavaScript/Fetch API](#javascriptfetch-api)
- [Axios](#axios)
- [React](#react)
- [Vue.js](#vuejs)
- [Angular](#angular)

---

## JavaScript/Fetch API

### Basic API Service Module

```javascript
// api.js
const API_BASE = 'http://127.0.0.1:8000/api';

export const api = {
  // Generic request method
  async request(endpoint, options = {}) {
    const defaultOptions = {
      headers: {
        'Content-Type': 'application/json',
      }
    };

    const config = { ...defaultOptions, ...options };
    const response = await fetch(`${API_BASE}${endpoint}`, config);
    
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || 'API Error');
    }
    
    return response.json();
  },

  // GET - Retrieve resource(s)
  get(endpoint) {
    return this.request(endpoint, { method: 'GET' });
  },

  // POST - Create resource
  post(endpoint, data) {
    return this.request(endpoint, {
      method: 'POST',
      body: JSON.stringify(data)
    });
  },

  // PUT - Update resource
  put(endpoint, data) {
    return this.request(endpoint, {
      method: 'PUT',
      body: JSON.stringify(data)
    });
  },

  // DELETE - Delete resource
  delete(endpoint) {
    return this.request(endpoint, { method: 'DELETE' });
  }
};

// Resource-specific functions
export const users = {
  list(skip = 0, limit = 10) {
    return api.get(`/users/?skip=${skip}&limit=${limit}`);
  },
  
  get(id) {
    return api.get(`/users/${id}/`);
  },
  
  create(data) {
    return api.post('/users/', data);
  },
  
  update(id, data) {
    return api.put(`/users/${id}/`, data);
  },
  
  delete(id) {
    return api.delete(`/users/${id}/`);
  },
  
  getProjects(id) {
    return api.get(`/users/${id}/projects/`);
  }
};

export const projects = {
  list(skip = 0, limit = 10) {
    return api.get(`/projects/?skip=${skip}&limit=${limit}`);
  },
  
  get(id) {
    return api.get(`/projects/${id}/`);
  },
  
  create(data) {
    return api.post('/projects/', data);
  },
  
  update(id, data) {
    return api.put(`/projects/${id}/`, data);
  },
  
  delete(id) {
    return api.delete(`/projects/${id}/`);
  },
  
  getSystems(id) {
    return api.get(`/projects/${id}/systems/`);
  }
};

export const components = {
  list(skip = 0, limit = 10) {
    return api.get(`/components/?skip=${skip}&limit=${limit}`);
  },
  
  get(id) {
    return api.get(`/components/${id}/`);
  },
  
  create(data) {
    return api.post('/components/', data);
  },
  
  update(id, data) {
    return api.put(`/components/${id}/`, data);
  },
  
  delete(id) {
    return api.delete(`/components/${id}/`);
  },
  
  getInventory(id) {
    return api.get(`/components/${id}/inventory/`);
  }
};

export const inventory = {
  list(skip = 0, limit = 10) {
    return api.get(`/inventory/?skip=${skip}&limit=${limit}`);
  },
  
  get(id) {
    return api.get(`/inventory/${id}/`);
  },
  
  create(data) {
    return api.post('/inventory/', data);
  },
  
  update(id, data) {
    return api.put(`/inventory/${id}/`, data);
  },
  
  delete(id) {
    return api.delete(`/inventory/${id}/`);
  }
};
```

### Usage in HTML/JavaScript

```html
<!DOCTYPE html>
<html>
<head>
  <title>PLCM - User Management</title>
</head>
<body>
  <div id="app">
    <h1>Users</h1>
    <button onclick="createUser()">Create User</button>
    <table id="usersTable">
      <thead>
        <tr>
          <th>ID</th>
          <th>Username</th>
          <th>Email</th>
          <th>Full Name</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody></tbody>
    </table>
  </div>

  <script type="module">
    import { users } from './api.js';

    // Load users on page load
    window.addEventListener('load', loadUsers);

    async function loadUsers() {
      try {
        const userList = await users.list(0, 10);
        const tbody = document.querySelector('#usersTable tbody');
        tbody.innerHTML = '';
        
        userList.forEach(user => {
          const row = tbody.insertRow();
          row.innerHTML = `
            <td>${user.id}</td>
            <td>${user.username}</td>
            <td>${user.email}</td>
            <td>${user.full_name}</td>
            <td>
              <button onclick="editUser(${user.id})">Edit</button>
              <button onclick="deleteUser(${user.id})">Delete</button>
            </td>
          `;
        });
      } catch (error) {
        alert('Error loading users: ' + error.message);
      }
    }

    window.createUser = async function() {
      const username = prompt('Username:');
      const email = prompt('Email:');
      const fullName = prompt('Full Name:');
      
      if (username && email && fullName) {
        try {
          await users.create({
            username,
            email,
            full_name: fullName,
            is_active: true
          });
          loadUsers();
          alert('User created successfully!');
        } catch (error) {
          alert('Error creating user: ' + error.message);
        }
      }
    };

    window.deleteUser = async function(id) {
      if (confirm('Are you sure?')) {
        try {
          await users.delete(id);
          loadUsers();
          alert('User deleted successfully!');
        } catch (error) {
          alert('Error deleting user: ' + error.message);
        }
      }
    };
  </script>
</body>
</html>
```

---

## Axios

### Installation

```bash
npm install axios
```

### API Service with Axios

```javascript
// api.js
import axios from 'axios';

const API_BASE = 'http://127.0.0.1:8000/api';

const instance = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json'
  }
});

// Error interceptor
instance.interceptors.response.use(
  response => response,
  error => {
    const message = error.response?.data?.detail || error.message;
    return Promise.reject(new Error(message));
  }
);

export const api = instance;

// Users API
export const usersAPI = {
  list: (skip = 0, limit = 10) => api.get(`/users/`, { params: { skip, limit } }),
  get: (id) => api.get(`/users/${id}/`),
  create: (data) => api.post('/users/', data),
  update: (id, data) => api.put(`/users/${id}/`, data),
  delete: (id) => api.delete(`/users/${id}/`),
  getProjects: (id) => api.get(`/users/${id}/projects/`)
};

// Projects API
export const projectsAPI = {
  list: (skip = 0, limit = 10) => api.get(`/projects/`, { params: { skip, limit } }),
  get: (id) => api.get(`/projects/${id}/`),
  create: (data) => api.post('/projects/', data),
  update: (id, data) => api.put(`/projects/${id}/`, data),
  delete: (id) => api.delete(`/projects/${id}/`),
  getSystems: (id) => api.get(`/projects/${id}/systems/`)
};

// Add more as needed...
export default api;
```

---

## React

### React Hooks Implementation

```javascript
// useAPI.js - Custom hook for API calls
import { useState, useEffect } from 'react';

export const useAPI = (url, method = 'GET', body = null) => {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!url) return;

    const fetchData = async () => {
      setLoading(true);
      setError(null);
      try {
        const options = {
          method,
          headers: { 'Content-Type': 'application/json' }
        };
        if (body) options.body = JSON.stringify(body);

        const response = await fetch(`http://127.0.0.1:8000/api${url}`, options);
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const result = await response.json();
        setData(result);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [url, method]);

  return { data, loading, error };
};

// UsersList.js - Component example
import React, { useState } from 'react';
import { useAPI } from './useAPI';

export function UsersList() {
  const [page, setPage] = useState(1);
  const pageSize = 10;
  const skip = (page - 1) * pageSize;
  
  const { data: users, loading, error } = useAPI(`/users/?skip=${skip}&limit=${pageSize}`);
  const [newUser, setNewUser] = useState({ username: '', email: '', full_name: '', is_active: true });

  const handleCreateUser = async () => {
    try {
      const response = await fetch('http://127.0.0.1:8000/api/users/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newUser)
      });
      if (response.ok) {
        setNewUser({ username: '', email: '', full_name: '', is_active: true });
        // Refresh the list
        window.location.reload();
      }
    } catch (err) {
      alert('Error creating user: ' + err.message);
    }
  };

  const handleDeleteUser = async (id) => {
    if (window.confirm('Delete this user?')) {
      try {
        await fetch(`http://127.0.0.1:8000/api/users/${id}/`, { method: 'DELETE' });
        window.location.reload();
      } catch (err) {
        alert('Error deleting user: ' + err.message);
      }
    }
  };

  if (loading) return <div>Loading...</div>;
  if (error) return <div>Error: {error}</div>;

  return (
    <div>
      <h1>Users</h1>
      
      <div className="create-form">
        <h2>Create New User</h2>
        <input
          type="text"
          placeholder="Username"
          value={newUser.username}
          onChange={(e) => setNewUser({ ...newUser, username: e.target.value })}
        />
        <input
          type="email"
          placeholder="Email"
          value={newUser.email}
          onChange={(e) => setNewUser({ ...newUser, email: e.target.value })}
        />
        <input
          type="text"
          placeholder="Full Name"
          value={newUser.full_name}
          onChange={(e) => setNewUser({ ...newUser, full_name: e.target.value })}
        />
        <button onClick={handleCreateUser}>Create User</button>
      </div>

      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Username</th>
            <th>Email</th>
            <th>Full Name</th>
            <th>Active</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {users?.map(user => (
            <tr key={user.id}>
              <td>{user.id}</td>
              <td>{user.username}</td>
              <td>{user.email}</td>
              <td>{user.full_name}</td>
              <td>{user.is_active ? 'Yes' : 'No'}</td>
              <td>
                <button onClick={() => handleDeleteUser(user.id)}>Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <div className="pagination">
        <button onClick={() => setPage(Math.max(1, page - 1))}>Previous</button>
        <span>Page {page}</span>
        <button onClick={() => setPage(page + 1)}>Next</button>
      </div>
    </div>
  );
}
```

### React with Context API

```javascript
// APIContext.js
import React, { createContext, useContext } from 'react';

const APIContext = createContext();

export function APIProvider({ children }) {
  const api = {
    users: {
      list: (skip = 0, limit = 10) =>
        fetch(`http://127.0.0.1:8000/api/users/?skip=${skip}&limit=${limit}`).then(r => r.json()),
      get: (id) => fetch(`http://127.0.0.1:8000/api/users/${id}/`).then(r => r.json()),
      create: (data) =>
        fetch('http://127.0.0.1:8000/api/users/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        }).then(r => r.json()),
      update: (id, data) =>
        fetch(`http://127.0.0.1:8000/api/users/${id}/`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data)
        }).then(r => r.json()),
      delete: (id) =>
        fetch(`http://127.0.0.1:8000/api/users/${id}/`, { method: 'DELETE' }).then(r => r.json())
    },
    projects: {
      list: (skip = 0, limit = 10) =>
        fetch(`http://127.0.0.1:8000/api/projects/?skip=${skip}&limit=${limit}`).then(r => r.json()),
      // ... other methods
    }
  };

  return <APIContext.Provider value={api}>{children}</APIContext.Provider>;
}

export function useAPI() {
  return useContext(APIContext);
}

// Usage
// function MyComponent() {
//   const api = useAPI();
//   const users = api.users.list();
// }
```

---

## Vue.js

### Vue 3 Composition API

```javascript
// useApi.js
import { ref } from 'vue';

export function useApi() {
  const API_BASE = 'http://127.0.0.1:8000/api';

  const get = async (endpoint) => {
    const response = await fetch(`${API_BASE}${endpoint}`);
    if (!response.ok) throw new Error('API Error');
    return response.json();
  };

  const post = async (endpoint, data) => {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    if (!response.ok) throw new Error('API Error');
    return response.json();
  };

  const put = async (endpoint, data) => {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data)
    });
    if (!response.ok) throw new Error('API Error');
    return response.json();
  };

  const delete_ = async (endpoint) => {
    const response = await fetch(`${API_BASE}${endpoint}`, { method: 'DELETE' });
    if (!response.ok) throw new Error('API Error');
    return response.json();
  };

  return { get, post, put, delete: delete_ };
}

// UsersList.vue
<template>
  <div>
    <h1>Users</h1>
    
    <div v-if="loading" class="loading">Loading...</div>
    <div v-if="error" class="error">{{ error }}</div>
    
    <div v-if="!loading && !error">
      <div class="form">
        <input v-model="newUser.username" placeholder="Username" />
        <input v-model="newUser.email" placeholder="Email" />
        <input v-model="newUser.full_name" placeholder="Full Name" />
        <button @click="createUser">Create</button>
      </div>

      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Username</th>
            <th>Email</th>
            <th>Full Name</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="user in users" :key="user.id">
            <td>{{ user.id }}</td>
            <td>{{ user.username }}</td>
            <td>{{ user.email }}</td>
            <td>{{ user.full_name }}</td>
            <td>
              <button @click="deleteUser(user.id)">Delete</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue';
import { useApi } from './useApi';

const api = useApi();
const users = ref([]);
const loading = ref(false);
const error = ref(null);
const newUser = ref({ username: '', email: '', full_name: '', is_active: true });

onMounted(async () => {
  await loadUsers();
});

async function loadUsers() {
  loading.value = true;
  error.value = null;
  try {
    users.value = await api.get('/users/?skip=0&limit=10');
  } catch (err) {
    error.value = err.message;
  } finally {
    loading.value = false;
  }
}

async function createUser() {
  if (!newUser.value.username || !newUser.value.email) {
    alert('Please fill all fields');
    return;
  }
  
  try {
    await api.post('/users/', newUser.value);
    newUser.value = { username: '', email: '', full_name: '', is_active: true };
    await loadUsers();
  } catch (err) {
    alert('Error: ' + err.message);
  }
}

async function deleteUser(id) {
  if (confirm('Delete user?')) {
    try {
      await api.delete(`/users/${id}/`);
      await loadUsers();
    } catch (err) {
      alert('Error: ' + err.message);
    }
  }
}
</script>
```

---

## Angular

### Angular Service Implementation

```typescript
// api.service.ts
import { Injectable } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface User {
  id?: number;
  username: string;
  email: string;
  full_name: string;
  is_active: boolean;
  created_at?: string;
  projects?: any[];
}

@Injectable({
  providedIn: 'root'
})
export class ApiService {
  private baseUrl = 'http://127.0.0.1:8000/api';

  constructor(private http: HttpClient) {}

  // Users
  getUsers(skip: number = 0, limit: number = 10): Observable<User[]> {
    const params = new HttpParams()
      .set('skip', skip)
      .set('limit', limit);
    return this.http.get<User[]>(`${this.baseUrl}/users/`, { params });
  }

  getUser(id: number): Observable<User> {
    return this.http.get<User>(`${this.baseUrl}/users/${id}/`);
  }

  createUser(user: User): Observable<User> {
    return this.http.post<User>(`${this.baseUrl}/users/`, user);
  }

  updateUser(id: number, user: Partial<User>): Observable<User> {
    return this.http.put<User>(`${this.baseUrl}/users/${id}/`, user);
  }

  deleteUser(id: number): Observable<any> {
    return this.http.delete(`${this.baseUrl}/users/${id}/`);
  }

  getUserProjects(id: number): Observable<any[]> {
    return this.http.get<any[]>(`${this.baseUrl}/users/${id}/projects/`);
  }
}

// users.component.ts
import { Component, OnInit } from '@angular/core';
import { ApiService, User } from './api.service';

@Component({
  selector: 'app-users',
  templateUrl: './users.component.html',
  styleUrls: ['./users.component.css']
})
export class UsersComponent implements OnInit {
  users: User[] = [];
  loading = false;
  error = '';
  newUser: User = {
    username: '',
    email: '',
    full_name: '',
    is_active: true
  };

  constructor(private api: ApiService) {}

  ngOnInit() {
    this.loadUsers();
  }

  loadUsers() {
    this.loading = true;
    this.error = '';
    this.api.getUsers(0, 10).subscribe({
      next: (data) => {
        this.users = data;
        this.loading = false;
      },
      error: (err) => {
        this.error = err.message;
        this.loading = false;
      }
    });
  }

  createUser() {
    if (!this.newUser.username || !this.newUser.email) {
      alert('Please fill all fields');
      return;
    }

    this.api.createUser(this.newUser).subscribe({
      next: () => {
        this.newUser = { username: '', email: '', full_name: '', is_active: true };
        this.loadUsers();
      },
      error: (err) => {
        alert('Error: ' + err.message);
      }
    });
  }

  deleteUser(id: number) {
    if (confirm('Delete user?')) {
      this.api.deleteUser(id).subscribe({
        next: () => {
          this.loadUsers();
        },
        error: (err) => {
          alert('Error: ' + err.message);
        }
      });
    }
  }
}

// users.component.html
<div>
  <h1>Users</h1>

  <div *ngIf="loading" class="loading">Loading...</div>
  <div *ngIf="error" class="error">{{ error }}</div>

  <div *ngIf="!loading && !error">
    <div class="form">
      <input
        [(ngModel)]="newUser.username"
        placeholder="Username"
        type="text"
      />
      <input
        [(ngModel)]="newUser.email"
        placeholder="Email"
        type="email"
      />
      <input
        [(ngModel)]="newUser.full_name"
        placeholder="Full Name"
        type="text"
      />
      <button (click)="createUser()">Create User</button>
    </div>

    <table>
      <thead>
        <tr>
          <th>ID</th>
          <th>Username</th>
          <th>Email</th>
          <th>Full Name</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        <tr *ngFor="let user of users">
          <td>{{ user.id }}</td>
          <td>{{ user.username }}</td>
          <td>{{ user.email }}</td>
          <td>{{ user.full_name }}</td>
          <td>
            <button (click)="deleteUser(user.id)">Delete</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
</div>
```

---

## Common Patterns & Best Practices

### Error Handling

```javascript
async function handleApiCall(apiFunction) {
  try {
    const result = await apiFunction();
    return { success: true, data: result };
  } catch (error) {
    return { 
      success: false, 
      error: error.message || 'Unknown error occurred' 
    };
  }
}

// Usage
const result = await handleApiCall(() => users.create({ ... }));
if (result.success) {
  console.log('Success:', result.data);
} else {
  console.log('Error:', result.error);
}
```

### Pagination

```javascript
class PaginationManager {
  constructor(pageSize = 10) {
    this.pageSize = pageSize;
    this.currentPage = 1;
  }

  get skip() {
    return (this.currentPage - 1) * this.pageSize;
  }

  nextPage() {
    this.currentPage++;
  }

  previousPage() {
    if (this.currentPage > 1) {
      this.currentPage--;
    }
  }

  setPage(page) {
    this.currentPage = Math.max(1, page);
  }
}
```

### Caching

```javascript
const cache = new Map();

async function getCachedData(key, fetcher) {
  if (cache.has(key)) {
    return cache.get(key);
  }

  const data = await fetcher();
  cache.set(key, data);
  return data;
}

// Usage
const projects = await getCachedData('projects', () => api.get('/projects/'));
```

---

## Testing the API

### Using Jest (Node.js)

```javascript
// api.test.js
import { users } from './api';

describe('Users API', () => {
  test('should list users', async () => {
    const result = await users.list();
    expect(Array.isArray(result)).toBe(true);
  });

  test('should get a specific user', async () => {
    const user = await users.get(1);
    expect(user).toHaveProperty('id');
    expect(user).toHaveProperty('username');
  });

  test('should create a user', async () => {
    const newUser = {
      username: 'testuser',
      email: 'test@example.com',
      full_name: 'Test User',
      is_active: true
    };
    const created = await users.create(newUser);
    expect(created).toHaveProperty('id');
  });
});
```

---

**Last Updated:** February 23, 2026
