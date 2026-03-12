import type { Model, Types } from 'mongoose';
import type { IAgentCategory } from '~/types';

export function createAgentCategoryMethods(mongoose: typeof import('mongoose')) {
  
  /**
   * Get unique deparments from user records
   */
  async function getUniqueUserDepartments(): Promise<string[]> {
    let validDepts: string[] =[];
    try {
      if (mongoose.connection.db) {
        const departments = await mongoose.connection.db.collection('users').distinct('departments');
        validDepts = departments
          .filter((d: any) => typeof d === 'string' && d.trim().length > 0)
          .map((d: any) => String(d).toUpperCase());
      }
    } catch (error) {
      console.error('[TAIA] Error fetching unique departments:', error);
    }

    if (!validDepts.some(d => d === 'GENERAL')) {
      validDepts.unshift('GENERAL');
    }

    return validDepts;
  }

  /**
   * Get all active categories
   */
  async function getActiveCategories(): Promise<IAgentCategory[]> {
    const uniqueDepartments = await getUniqueUserDepartments();
    return uniqueDepartments.map((dept) => ({
      value: dept.toUpperCase(),
      label: dept,
      description: `${dept} Department`,
      isActive: true,
      custom: true,
    } as IAgentCategory));
  }

  /**
   * Get categories with agent counts
   */
  async function getCategoriesWithCounts(): Promise<(IAgentCategory & { agentCount: number })[]> {
    const Agent = mongoose.models.Agent;

    const categoryCounts = await Agent.aggregate([
      { $match: { category: { $exists: true, $ne: null } } },
      { $group: { _id: '$category', count: { $sum: 1 } } },
    ]);

    const countMap = new Map(categoryCounts.map((c) => [c._id, c.count]));
    const categories = await getActiveCategories();

    return categories.map((category) => ({
      ...category,
      agentCount: countMap.get(category.value) || (0 as number),
    })) as (IAgentCategory & { agentCount: number })[];
  }

  /**
   * Get valid category values for Agent model validation
   */
  async function getValidCategoryValues(): Promise<string[]> {
    const uniqueDepartments = await getUniqueUserDepartments();
    return uniqueDepartments.map((dept) => dept.toUpperCase());
  }

  /**
   * Find a category by value
   */
  async function findCategoryByValue(value: string): Promise<IAgentCategory | null> {
    const uniqueDepartments = await getUniqueUserDepartments();
    const match = uniqueDepartments.find((d) => d.toUpperCase() === value.toUpperCase());
    
    if (match) {
      return {
        value: match.toUpperCase(),
        label: match,
        description: `${match} Department`,
        isActive: true,
        custom: true,
      } as IAgentCategory;
    }
    return null;
  }

  /**
   * Get all categories (Same as active for TAIA)
   */
  async function getAllCategories(): Promise<IAgentCategory[]> {
    return await getActiveCategories();
  }

  /**
   * Bypass Default Seeding
   */
  async function ensureDefaultCategories(): Promise<boolean> {
    // Return false to prevent LibreChat from trying to inject its default categories
    return false;
  }

  // --- Mock functions to prevent LibreChat errors if it tries to write to the DB ---
  async function seedCategories(): Promise<any> { return { insertedCount: 0 }; }
  async function createCategory(data: any): Promise<any> { return data; }
  async function updateCategory(): Promise<any> { return null; }
  async function deleteCategory(): Promise<boolean> { return true; }
  async function findCategoryById(): Promise<any> { return null; }

  return {
    getActiveCategories,
    getCategoriesWithCounts,
    getValidCategoryValues,
    seedCategories,
    findCategoryByValue,
    createCategory,
    updateCategory,
    deleteCategory,
    findCategoryById,
    getAllCategories,
    ensureDefaultCategories,
  };
}

export type AgentCategoryMethods = ReturnType<typeof createAgentCategoryMethods>;