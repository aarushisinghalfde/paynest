"""Common first names (Indian and Arab) in Latin, Devanagari and Arabic script.

Used to catch a first name standing alone ("Ananya will send it", "اتصل بخالد").
Names that are also everyday words are left out on purpose so ordinary text is not masked:
Hope, May, Joy; पूजा "worship", निधि "fund" (भविष्य निधि), सीमा "limit", विजय "victory";
حمد (الحمد لله), مبارك (عيد مبارك), عمر "age", حسن "good", صالح "valid", هند (الهند).
Rare names fall back to the context cues and to spaCy.
"""

LATIN = frozenset("""
aarav aditya akash akshay alok aman amar amit amitabh amol anand anil anirudh ankit ankur anshul
anuj anupam arjun arnav arun ashish ashok ashwin atul ayush deepak dev dhruv dinesh gaurav girish
gopal harish harsh hemant ishaan jatin jayant karan kartik kishore krishna kunal lalit madhav mahesh
manish manoj mayank mohit mukesh nakul naveen neeraj nikhil nitin omkar pankaj paras pranav prakash
pramod prashant prateek pratik puneet rahul raj rajat rajesh rajiv rakesh ramesh ravi rishabh ritesh
rohan rohit sachin sahil samir sandeep sanjay santosh saurabh shashank shekhar shivam shreyas shubham
siddharth sudhir sumit sunil suresh tarun tushar uday varun vijay vikas vikram vinay vinod vishal
vivek yash yogesh zubin abhishek abhinav vaibhav venkat srinivas raghav naresh mahendra
aanya aditi ananya anjali ankita anita anu aparna archana arti bhavna chitra deepa deepika divya
gayatri geeta isha ishita jyoti kajal kavita kavya komal kriti lakshmi madhuri mamta manisha meena
meera megha monika nandini neha nidhi nikita nisha pallavi pooja poonam preeti priya priyanka rachna
radha rashmi rekha renu ritu riya sakshi sangeeta sanjana sapna sarita shalini shikha shilpa shreya
shweta simran sneha sonal sonam sunita swati tanvi tanya trisha usha vandana varsha vidya
ahmed ahmad mohammed mohammad muhammad omar umar ali hassan hussein hasan husain khalid khaled
yousef yusuf youssef ibrahim abdullah abdulla abdulrahman hamdan hamad hamid rashid rashed saeed
sultan majid mansour faisal fahad tariq waleed walid zayed mubarak saif salem saleh nasser jassim
fatima fatma aisha ayesha mariam maryam noura nora layla laila huda hessa hind latifa reem shamma
salma sara sarah zainab khadija amna mona rania dana lina asma alia aaliya
""".split())

DEVANAGARI = frozenset("""
राहुल अमित विक्रम अर्जुन रोहन संजय सुरेश रमेश दिनेश महेश राजेश मनोज अनिल सुनील अजय
अभिषेक आदित्य निखिल सौरभ विवेक अशोक नरेश योगेश हरीश सचिन विनोद मुकेश
प्रिया अनन्या स्नेहा काव्या मीरा नेहा अंजलि दिव्या सुनीता
प्रियंका श्वेता पल्लवी स्वाति शालिनी मोनिका अनीता सरिता
""".split())

ARABIC = frozenset("""
أحمد محمد علي حسين خالد يوسف إبراهيم عبدالله حمدان حامد راشد سلطان منصور
فيصل فهد طارق وليد زايد ناصر جاسم عبدالرحمن
فاطمة عائشة مريم نورة ليلى حصة لطيفة ريم شمة سلمى سارة زينب خديجة آمنة رانيا
""".split())
