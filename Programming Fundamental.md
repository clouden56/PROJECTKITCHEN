# **Fridge Recipe Tracker**

**1\. Problem Statement and Target Users**

* What real-world problem does your application aim to solve?

  Nowadays, people often have a mix of ingredients sitting in their fridge but are unsure what to cook with them. This leads to three recurring and detrimental issues. **Food Wastage**, ingredients expire and spoil in the fridge before they are used. **Unnecessary Spending,** buying groceries are a weekly recurring cost, and without proper planning around how existing ingredients are used will result in significant, avoidable financial loss over time. **Decision Fatigue**, the daily struggle of deciding what to eat, even when usable ingredients are already sitting in the fridge. 

  The **Fridge Recipe Tracker** helps solve these real-world problems by showing users what they can cook with the ingredients they already have, instead of letting food sit unused until it spoils. By logging the fridge ingredients and expiry date alongside meal type and available cooking time, users instantly receive recipe suggestions that prioritize soon-to-expire items. Which helps to prevent food wastage, cutting weekly grocery spending, and removing the daily guesswork of meal planning.

**2\. User Inputs**

* What information or data will users provide to the system?  
1. Types of Ingredients: Select the food item that the user have in their fridge/house (**E.g., Eggs, Milk, Cheese, Lettuce,Bread**)  
2. Expiry as per Ingredients: The date on the ingredients, so they can prioritize which ingredient should be cooked first  
3. Meal Type: **Breakfast, Lunch & Dinner or Snack**  
4. Time Constraint: How much time the user has to cook (**E.g., Under 15 minutes/ 30 minutes**). Therefore, the recipe fits their schedule.

**3\. Use of AI**

* How will AI be utilized within the application?  
- AI will search through the web and craft recipes based on:  
  - User’s ingredients inputs  
  - Expiry dates of ingredients  
  - Meal Type  
  - Time Constraint  
  - Matched score/percentage for matching 


* What outputs, insights, or recommendations will the AI generate from the user inputs?  
  Output \- recipe of food  
  Input \- ingredients that is inside the fridge 

**4\. Business Rules**

* What business rules, validations, or decision-making logic will be applied to the AI-generated outputs?  
  * Constraints for safety and dietary restriction \- should a user specify an allergy or lactose intolerance by no means  should the app recommend peanut dishes for examples  
  * Add priority recommendation \- should the user specify expiry date, app should prioritise things where the expiry date is coming up soon.  
  * Minimum input- there should be a minimum number of ingredients inputted before a valid output can be provided  
  * If the recipe is close to a match, recipe should still show while stating which ingredient is/are missing  
  * Recipe Threshold \- there's a threshold percentage of the recipe’s ingredients that the user has for it to be considered a match 

![][image1]  
**Pitch:**

Problem \- People rarely see value in their leftover/untouched ingredients in their fridge when they can always be used as ingredients for delicious meal recipes  
Solution \- AI powered recipe tracker that uses fridge inputs, expiry dates, and cooking time to suggest meals.   
Impact \- Saves time, reduces waste, and makes meal planning effortless.   
Standout point \- Very simple yet effective way to reduce food wastage and prevents users from throwing away ingredients unnecessarily 

**Data flow:**

 ![][image2]

**Github Repository URL**

[https://github.com/Kririn10/INF1103-PROJECT.git](https://github.com/Kririn10/INF1103-PROJECT.git) 

Recommandation  
Feedback   
not limited to fridge, we can add for the pantry like the dry ingredient

specified ingredient measurement like (1 tbs of something) 

by the internet by giving recommendation of the way it cook (stir-fry)

will it take what cooking pot / materials 

accuracy of the user input  with some range of the expiry date (plus maybe 3 days)

