import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface Unit {
  id: string;
  code: string;
  name: string;
  is_active: boolean;
}

export interface Sector {
  id: string;
  unit_id: string;
  code: string;
  name: string;
  is_active: boolean;
  unit?: Unit;
}

export interface Employee {
  id: string;
  registration: string;
  name: string;
  sector_id: string;
  job_title: string;
  is_active: boolean;
  sector?: Sector;
}

@Injectable({
  providedIn: 'root'
})
export class OrganizationService {
  private http = inject(HttpClient);
  private baseUrl = '/api/v1/organization';

  // Company
  getCompanyPublic(): Observable<{ name: string; logo_url: string | null }> {
    return this.http.get<{ name: string; logo_url: string | null }>(`${this.baseUrl}/company/public`);
  }

  // Units
  getUnits(): Observable<Unit[]> {
    return this.http.get<Unit[]>(`${this.baseUrl}/units`);
  }

  createUnit(data: any): Observable<Unit> {
    return this.http.post<Unit>(`${this.baseUrl}/units`, data);
  }

  updateUnit(id: string, data: any): Observable<Unit> {
    return this.http.patch<Unit>(`${this.baseUrl}/units/${id}`, data);
  }

  deleteUnit(id: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/units/${id}`);
  }

  // Sectors
  getSectors(): Observable<Sector[]> {
    return this.http.get<Sector[]>(`${this.baseUrl}/sectors`);
  }

  createSector(data: any): Observable<Sector> {
    return this.http.post<Sector>(`${this.baseUrl}/sectors`, data);
  }

  updateSector(id: string, data: any): Observable<Sector> {
    return this.http.patch<Sector>(`${this.baseUrl}/sectors/${id}`, data);
  }

  deleteSector(id: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/sectors/${id}`);
  }

  // Employees
  getEmployees(): Observable<Employee[]> {
    return this.http.get<Employee[]>(`${this.baseUrl}/employees`);
  }

  createEmployee(data: any): Observable<Employee> {
    return this.http.post<Employee>(`${this.baseUrl}/employees`, data);
  }

  updateEmployee(id: string, data: any): Observable<Employee> {
    return this.http.patch<Employee>(`${this.baseUrl}/employees/${id}`, data);
  }

  deleteEmployee(id: string): Observable<void> {
    return this.http.delete<void>(`${this.baseUrl}/employees/${id}`);
  }
}
