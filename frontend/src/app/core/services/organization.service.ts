import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, Observable } from 'rxjs';

export interface Company {
  id: string;
  name: string;
  cnpj: string | null;
  logo_url: string | null;
}

/** Nome e logo exibidos no menu e na tela de login (endpoint público). */
export interface Branding {
  name: string;
  logo_url: string | null;
}

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
  registration_number?: string;
  name: string;
  sector_id: string;
  job_title: string;
  phone?: string | null;
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
  /** Marca atual; o menu e o login assinam, a tela da empresa atualiza ao salvar. */
  readonly branding$ = new BehaviorSubject<Branding | null>(null);

  getCompanyPublic(): Observable<Branding> {
    return this.http.get<Branding>(`${this.baseUrl}/company/public`);
  }

  loadBranding(): void {
    this.getCompanyPublic().subscribe({
      next: (branding) => this.branding$.next(branding),
      error: () => {} // sem a marca o sistema continua com o nome padrão
    });
  }

  getCompany(): Observable<Company> {
    return this.http.get<Company>(`${this.baseUrl}/company`);
  }

  updateCompany(data: { name?: string; cnpj?: string | null }): Observable<Company> {
    return this.http.patch<Company>(`${this.baseUrl}/company`, data);
  }

  uploadCompanyLogo(file: File): Observable<{ logo_url: string; message: string }> {
    const form = new FormData();
    form.append('file', file);
    return this.http.post<{ logo_url: string; message: string }>(`${this.baseUrl}/company/logo`, form);
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
